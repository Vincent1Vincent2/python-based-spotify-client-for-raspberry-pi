import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import Client, SimpleTestCase, TestCase

from player.features.library_home.home import (
    RECENT_LIMIT,
    LibraryHomeScopeError,
    load_home,
    parse_recently_played,
)
from player.models import SpotifyAccount
from player.spotify_api import SpotifyAPI
from player.views import SPOTIFY_SCOPE


EXISTING_SCOPES = (
    "user-modify-playback-state",
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-read-playback-position",
    "streaming",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "user-library-read",
)


def _track(track_id, name, artists, album="Album", played_at="2026-11-04T12:00:00.000Z"):
    return {
        "played_at": played_at,
        "context": {"type": "playlist", "uri": "spotify:playlist:should-not-be-fetched"},
        "track": {
            "id": track_id,
            "uri": f"spotify:track:{track_id}",
            "name": name,
            "duration_ms": 180000,
            "artists": [
                {"id": artist_id, "name": artist_name}
                for artist_id, artist_name in artists
            ],
            "album": {
                "name": album,
                "images": [{"url": f"https://i.scdn.co/image/{track_id}"}],
            },
        },
    }


RECENT_PAYLOAD = {
    "items": [
        _track(
            "abc",
            "Blue Monday",
            [("new-order", "New Order")],
            album="Power, Corruption & Lies",
            played_at="2026-11-04T12:00:00.000Z",
        ),
        {"played_at": "2026-11-04T11:00:00.000Z", "track": None},
        "not-a-play",
        _track(
            "def",
            "Age of Consent",
            [("new-order", "New Order"), ("guest", "Guest")],
            album="Power, Corruption & Lies",
            played_at="2026-11-04T11:30:00.000Z",
        ),
    ],
    "next": "https://api.spotify.com/v1/me/player/recently-played?before=1&limit=50",
    "cursors": {"before": "1", "after": "2"},
    "limit": 50,
    "href": "https://api.spotify.com/v1/me/player/recently-played?limit=50",
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class FakeAPI:
    def __init__(self, payload=None, status=200):
        self.payload = {"items": []} if payload is None else payload
        self.status = status
        self.calls = []

    def get(self, endpoint, params=None, **kwargs):
        self.calls.append((endpoint, params))
        return FakeResponse(self.payload, self.status)

    def get_recently_played(self, *args, **kwargs):
        raise AssertionError("the home strip must not use the 50-item helper")


class ParseRecentlyPlayedTests(SimpleTestCase):
    def test_rows_keep_order_and_skip_empty_tracks(self):
        rows = parse_recently_played(RECENT_PAYLOAD)
        self.assertEqual(
            [(row["name"], row["artists"], row["played_at"]) for row in rows],
            [
                ("Blue Monday", ["New Order"], "2026-11-04T12:00:00.000Z"),
                ("Age of Consent", ["New Order", "Guest"], "2026-11-04T11:30:00.000Z"),
            ],
        )
        self.assertEqual(rows[0]["album"], "Power, Corruption & Lies")
        self.assertEqual(rows[0]["uri"], "spotify:track:abc")
        self.assertEqual(rows[0]["image"], "https://i.scdn.co/image/abc")
        self.assertLessEqual(len(rows), RECENT_LIMIT)

    def test_garbage_payload_is_an_empty_strip(self):
        self.assertEqual(parse_recently_played(None), [])
        self.assertEqual(parse_recently_played({}), [])
        self.assertEqual(parse_recently_played({"items": None}), [])


class LoadHomeTests(SimpleTestCase):
    def test_one_read_with_limit_10(self):
        api = FakeAPI(RECENT_PAYLOAD)
        result = load_home(api)
        self.assertEqual(api.calls, [("me/player/recently-played", {"limit": 10})])
        self.assertEqual(result["limit"], 10)
        self.assertEqual(result["reads"], ["GET /me/player/recently-played?limit=10"])
        self.assertEqual(result["items"][0]["name"], "Blue Monday")
        self.assertNotIn("recommendations", result)
        self.assertNotIn("next", result)

    def test_forbidden_raises_needs_scope(self):
        api = FakeAPI(status=403)
        with self.assertRaises(LibraryHomeScopeError) as caught:
            load_home(api)
        self.assertEqual(caught.exception.code, "needs_scope")
        self.assertEqual(api.calls, [("me/player/recently-played", {"limit": 10})])


class LibraryHomeScopeTests(SimpleTestCase):
    def test_scope_adds_recently_played_and_keeps_the_rest(self):
        scopes = SPOTIFY_SCOPE.split()
        self.assertEqual(
            set(scopes),
            set(EXISTING_SCOPES) | {"user-read-recently-played"},
        )
        self.assertIn("playlist-modify-private", scopes)
        self.assertIn("user-read-recently-played", scopes)
        self.assertEqual(len(scopes), len(set(scopes)))
        self.assertEqual(scopes[-1], "user-read-recently-played")


def _account(spotify_user_id):
    return SpotifyAccount.objects.create(
        spotify_user_id=spotify_user_id,
        display_name="Listener",
        access_token="access",
        refresh_token="refresh",
        token_expires_at=time.time() + 3600,
    )


def _client_for(account):
    client = Client()
    session = client.session
    session["active_account_id"] = account.id
    session["use_web_player"] = True
    session.save()
    return client


class LibraryHomeViewTests(TestCase):
    def test_view_parses_recently_played_payload_and_does_not_request_limit_above_10(self):
        client = _client_for(_account("home-user"))
        calls = []

        def fake_get(self, endpoint, params=None, **kwargs):
            calls.append({
                "endpoint": endpoint,
                "params": {} if params is None else dict(params),
            })
            return FakeResponse(RECENT_PAYLOAD)

        with patch.object(SpotifyAPI, "get", fake_get), \
                patch.object(
                    SpotifyAPI,
                    "get_recently_played",
                    side_effect=AssertionError("limit 50 helper"),
                    create=True,
                ):
            response = client.get("/home/?limit=50")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["endpoint"], "me/player/recently-played")
        self.assertEqual(set(calls[0]["params"]), {"limit"})
        self.assertLessEqual(int(calls[0]["params"]["limit"]), 10)
        self.assertEqual(int(calls[0]["params"]["limit"]), 10)
        body = response.json()
        self.assertEqual(body["items"][0]["name"], "Blue Monday")
        self.assertEqual(body["items"][0]["artists"], ["New Order"])
        self.assertEqual(body["items"][0]["album"], "Power, Corruption & Lies")
        self.assertEqual(body["items"][0]["played_at"], "2026-11-04T12:00:00.000Z")
        self.assertEqual(body["items"][1]["name"], "Age of Consent")
        self.assertEqual(len(body["items"]), 2)
        self.assertNotIn("recommendations", body)
        self.assertNotIn("next", body)
        self.assertNotIn("recommend", response.content.decode())

    def test_forbidden_returns_needs_scope_and_reauth_url(self):
        client = _client_for(_account("home-forbidden"))
        calls = []

        def fake_get(self, endpoint, params=None, **kwargs):
            calls.append((endpoint, params))
            return FakeResponse(
                {"error": {"status": 403, "message": "Insufficient client scope"}},
                403,
            )

        with patch.object(SpotifyAPI, "get", fake_get):
            response = client.get("/home/")

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data["code"], "needs_scope")
        self.assertEqual(data["login_url"], "/login/?auth=1")
        self.assertIn("/login/?auth=1", response.content.decode())
        self.assertEqual(calls, [("me/player/recently-played", {"limit": 10})])

    def test_missing_session_is_unauthorized(self):
        response = Client().get("/home/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")

    def test_logged_in_auth_link_starts_oauth_with_the_new_scope(self):
        client = _client_for(_account("home-reauth"))
        home = client.get("/login/")
        self.assertRedirects(home, "/")
        reconnect = client.get("/login/?auth=1")
        self.assertEqual(reconnect.status_code, 302)
        location = reconnect["Location"]
        self.assertIn("https://accounts.spotify.com/authorize?", location)
        scopes = set(parse_qs(urlparse(location).query)["scope"][0].split())
        self.assertIn("user-read-recently-played", scopes)
        for scope in EXISTING_SCOPES:
            self.assertIn(scope, scopes)


class LibraryHomePageTests(TestCase):
    def test_playlists_stay_the_default_and_feel_button_is_local(self):
        client = _client_for(_account("home-page"))
        spotify_gets = []

        def fake_get(self, endpoint, params=None, **kwargs):
            spotify_gets.append(endpoint)
            raise AssertionError(endpoint)

        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)), \
                patch("player.spotify_api.SpotifyAPI.get", fake_get):
            page = client.get("/")

        self.assertEqual(page.status_code, 200)
        self.assertEqual(spotify_gets, [])
        body = page.content.decode()
        self.assertIn(
            '<button class="tab-button active" onclick="switchTab(\'playlists\')"',
            body,
        )
        self.assertIn('id="tab-playlists">Playlists</button>', body)
        self.assertIn(
            '<button class="tab-button" onclick="switchTab(\'home\')" id="tab-home">Home</button>',
            body,
        )
        self.assertNotRegex(body, r'id="tab-home"[^>]*\bactive\b')
        self.assertIn('<div class="tab-content active" id="content-playlists">', body)
        self.assertIn('<div class="tab-content" id="content-home">', body)
        self.assertNotIn('<div class="tab-content active" id="content-home">', body)
        self.assertRegex(
            body,
            r'<button class="btn" id="homeFeel" type="button" onclick="switchTab\(\'feel\'\)">',
        )
        self.assertRegex(
            body,
            r"window\.addEventListener\('load', \(\) => \{\s*loadPlaylists\(true\);\s*\}\);",
        )
        self.assertIn("fetch('/home/')", body)
        self.assertIn("/login/?auth=1", body)
        self.assertIn("Feel radio", body)
        self.assertNotIn("recommendations", body.lower())
