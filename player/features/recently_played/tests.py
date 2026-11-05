import time
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase

from player.features.recently_played import (
    LOGIN_PATH,
    SCOPE,
    NeedsScope,
    load_recently_played,
    play_recent,
)
from player.models import SpotifyAccount
from player.views import SPOTIFY_SCOPE


PAYLOAD = {
    "items": [
        {
            "track": {
                "id": "aaa",
                "uri": "spotify:track:aaa",
                "name": "Night Drive",
                "artists": [{"name": "Ada"}, {"name": "Bea"}],
                "album": {
                    "name": "Late",
                    "images": [{"url": "https://i.scdn.co/image/aaa"}],
                },
            },
            "played_at": "2026-11-04T18:00:00.000Z",
            "context": {"type": "playlist", "uri": "spotify:playlist:zzz"},
        },
        {
            "track": {
                "id": "bbb",
                "uri": "spotify:track:bbb",
                "name": "Morning",
                "artists": [{"name": "Cal"}],
                "album": {"name": "Early", "images": []},
            },
            "played_at": "2026-11-04T17:00:00.000Z",
        },
        {
            "track": {
                "id": "ccc",
                "uri": "spotify:track:ccc",
                "name": "Noon",
                "artists": [{"name": "Dee"}],
                "album": {
                    "name": "Mid",
                    "images": [{"url": "https://i.scdn.co/image/ccc"}],
                },
            },
            "played_at": "2026-11-03T12:30:00.000Z",
        },
    ],
    "next": "https://api.spotify.com/v1/me/player/recently-played?before=cursor",
    "cursors": {"after": "after", "before": "before"},
    "limit": 50,
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
        self.payload = PAYLOAD if payload is None else payload
        self.status = status
        self.gets = []
        self.plays = []

    def get(self, endpoint, params=None, **kwargs):
        self.gets.append((endpoint, params))
        return FakeResponse(self.payload, self.status)

    def start_playback(
        self,
        device_id=None,
        context_uri=None,
        uris=None,
        offset=None,
        position_ms=None,
    ):
        self.plays.append({
            "device_id": device_id,
            "context_uri": context_uri,
            "uris": uris,
            "offset": offset,
            "position_ms": position_ms,
        })
        return FakeResponse({}, status=204)


class RecentlyPlayedPayloadTests(SimpleTestCase):
    def test_three_item_payload_lists_track_artists_and_played_at(self):
        api = FakeAPI(PAYLOAD)
        items = load_recently_played(api)

        self.assertEqual(len(items), 3)
        self.assertEqual(
            [(item["track"], item["artists"], item["played_at"], item["uri"]) for item in items],
            [
                ("Night Drive", ["Ada", "Bea"], "2026-11-04T18:00:00.000Z", "spotify:track:aaa"),
                ("Morning", ["Cal"], "2026-11-04T17:00:00.000Z", "spotify:track:bbb"),
                ("Noon", ["Dee"], "2026-11-03T12:30:00.000Z", "spotify:track:ccc"),
            ],
        )
        self.assertEqual(api.gets, [("me/player/recently-played", {"limit": 50})])
        self.assertEqual(api.plays, [])

    def test_forbidden_read_needs_the_recently_played_scope(self):
        api = FakeAPI(status=403)
        with self.assertRaises(NeedsScope) as caught:
            load_recently_played(api)
        self.assertEqual(caught.exception.code, "needs_scope")
        self.assertEqual(caught.exception.login, LOGIN_PATH)
        self.assertEqual(len(api.gets), 1)
        self.assertEqual(api.plays, [])

    def test_play_uses_that_uri_only(self):
        api = FakeAPI(PAYLOAD)
        result = play_recent(api, "spotify:track:bbb")
        self.assertEqual(result["status"], "playing")
        self.assertEqual(result["uri"], "spotify:track:bbb")
        self.assertEqual(api.gets, [])
        self.assertEqual(len(api.plays), 1)
        self.assertEqual(api.plays[0]["uris"], ["spotify:track:bbb"])
        self.assertIsNone(api.plays[0]["context_uri"])
        self.assertIsNone(api.plays[0]["offset"])


class RecentlyPlayedViewTests(TestCase):
    def test_get_returns_the_three_rows_from_one_read(self):
        api = FakeAPI(PAYLOAD)
        with patch(
            "player.features.recently_played.views.get_spotify_api",
            return_value=api,
        ):
            response = Client().get("/recently-played/")

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["track"], "Night Drive")
        self.assertEqual(items[0]["artists"], ["Ada", "Bea"])
        self.assertEqual(items[0]["played_at"], "2026-11-04T18:00:00.000Z")
        self.assertEqual(items[2]["track"], "Noon")
        self.assertEqual(items[2]["artists"], ["Dee"])
        self.assertEqual(
            [item["played_at"] for item in items],
            [
                "2026-11-04T18:00:00.000Z",
                "2026-11-04T17:00:00.000Z",
                "2026-11-03T12:30:00.000Z",
            ],
        )
        self.assertEqual(api.gets, [("me/player/recently-played", {"limit": 50})])
        self.assertEqual(api.plays, [])

    def test_forbidden_read_returns_needs_scope_and_login(self):
        api = FakeAPI(status=403)
        with patch(
            "player.features.recently_played.views.get_spotify_api",
            return_value=api,
        ):
            response = Client().get("/recently-played/")

        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["code"], "needs_scope")
        self.assertEqual(body["login"], "/login/?auth=1")
        self.assertEqual(api.gets, [("me/player/recently-played", {"limit": 50})])

    def test_play_row_calls_start_playback_with_that_uri(self):
        api = FakeAPI(PAYLOAD)
        with patch(
            "player.features.recently_played.views.get_spotify_api",
            return_value=api,
        ):
            response = Client().post("/recently-played/play/?uri=spotify:track:ccc")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["uri"], "spotify:track:ccc")
        self.assertEqual(api.plays[0]["uris"], ["spotify:track:ccc"])
        self.assertIsNone(api.plays[0]["context_uri"])
        self.assertEqual(api.gets, [])

    def test_play_forwards_the_web_player_device(self):
        api = FakeAPI(PAYLOAD)
        client = Client()
        session = client.session
        session["use_web_player"] = True
        session.save()
        with patch(
            "player.features.recently_played.views.get_spotify_api",
            return_value=api,
        ):
            response = client.post(
                "/recently-played/play/?uri=spotify:track:aaa&device_id=web-1"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(api.plays[0]["device_id"], "web-1")
        self.assertEqual(api.plays[0]["uris"], ["spotify:track:aaa"])

    def test_play_without_a_uri_does_not_start_playback(self):
        api = FakeAPI(PAYLOAD)
        with patch(
            "player.features.recently_played.views.get_spotify_api",
            return_value=api,
        ):
            response = Client().post("/recently-played/play/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(api.plays, [])

    def test_signed_out_list_is_unauthorized(self):
        response = Client().get("/recently-played/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")


class RecentlyPlayedScopeTests(SimpleTestCase):
    def test_scope_adds_recently_played_without_removing_existing(self):
        scopes = SPOTIFY_SCOPE.split()
        existing = [
            "user-modify-playback-state",
            "user-read-playback-state",
            "user-read-currently-playing",
            "user-read-playback-position",
            "streaming",
            "playlist-read-private",
            "playlist-read-collaborative",
            "playlist-modify-private",
            "user-library-read",
        ]
        self.assertIn(SCOPE, scopes)
        self.assertEqual(scopes.count(SCOPE), 1)
        for scope in existing:
            self.assertIn(scope, scopes)
        self.assertEqual(len(scopes), len(existing) + 1)


class RecentlyPlayedPageTests(TestCase):
    def _account(self):
        return SpotifyAccount.objects.create(
            spotify_user_id="recent-user",
            display_name="Recent",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )

    def _signed_in(self):
        account = self._account()
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session["use_web_player"] = True
        session.save()
        return client

    def test_player_page_has_a_recent_tab(self):
        client = self._signed_in()
        with patch(
            "player.spotify_api.SpotifyAPI.get_devices",
            return_value=FakeResponse({"devices": []}),
        ), patch(
            "player.spotify_api.SpotifyAPI.get_current_playback",
            return_value=FakeResponse({}, status=204),
        ):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="tab-recent"', body)
        self.assertIn(">Recent</button>", body)
        self.assertIn('id="content-recent"', body)
        self.assertIn("loadRecent", body)
        self.assertIn("/recently-played/", body)
        self.assertIn("Reconnect Spotify to show recently played tracks.", body)
        self.assertIn('href="/login/?auth=1"', body)

    def test_signed_in_login_without_auth_stays_on_the_player(self):
        response = self._signed_in().get("/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_signed_in_auth_query_reauthorizes_with_the_new_scope(self):
        response = self._signed_in().get("/login/?auth=1")
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertIn("https://accounts.spotify.com/authorize", location)
        self.assertIn("user-read-recently-played", location)
        self.assertIn("user-library-read", location)
        self.assertIn("playlist-modify-private", location)
        self.assertIn("user-modify-playback-state", location)
