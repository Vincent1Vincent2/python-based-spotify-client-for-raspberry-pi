"""Fakes for heavy rotation: one read per click, limit 10, range passed through."""

import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import Client, TestCase

from player.features.top_rotation.rotation import (
    LOGIN_LINK,
    TopRotationError,
    load_top,
)
from player.models import SpotifyAccount
from player.views import SPOTIFY_SCOPE


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload


class RecordingAPI:
    """Records every Spotify read. Only ``get`` exists, so a second API is an error."""

    def __init__(self, payload=None, status=200):
        self.payload = {"items": []} if payload is None else payload
        self.status = status
        self.calls = []

    def get(self, endpoint, params=None, **kwargs):
        query = dict(params or {})
        self.calls.append((endpoint, query))
        return FakeResponse(self.payload, self.status)


def _track(number=1):
    return {
        "id": f"t{number}",
        "uri": f"spotify:track:t{number}",
        "name": f"Night Drive {number}",
        "artists": [{"name": "Ada"}, {"name": "Bea"}],
        "album": {"name": "After", "images": [{"url": "https://i.scdn.co/track"}]},
        "duration_ms": 180000,
    }


def _artist(number=1):
    return {
        "id": f"a{number}",
        "uri": f"spotify:artist:a{number}",
        "name": f"Ada {number}",
        "genres": ["piano", "night"],
        "images": [{"url": "https://i.scdn.co/artist"}],
    }


class TopRotationReadTests(TestCase):
    def test_each_click_is_one_read_and_the_range_is_passed_through(self):
        api = RecordingAPI()
        client = Client()
        ranges = ("short_term", "medium_term", "long_term")
        kinds = (("tracks", "me/top/tracks"), ("artists", "me/top/artists"))
        with patch("player.features.top_rotation.views.get_spotify_api", return_value=api):
            for kind, endpoint in kinds:
                for time_range in ranges:
                    before = len(api.calls)
                    response = client.get(f"/rotation/{kind}/?time_range={time_range}&limit=50")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(len(api.calls) - before, 1)
                    path, params = api.calls[-1]
                    self.assertEqual(path, endpoint)
                    self.assertLessEqual(params["limit"], 10)
                    self.assertEqual(params["limit"], 10)
                    self.assertEqual(params["time_range"], time_range)
                    self.assertNotIn("offset", params)
                    self.assertEqual(
                        response.json()["reads"],
                        [f"GET /{endpoint}?limit=10&time_range={time_range}"],
                    )

    def test_a_tracks_click_does_not_read_artists(self):
        api = RecordingAPI({"items": [_track()]})
        client = Client()
        with patch("player.features.top_rotation.views.get_spotify_api", return_value=api):
            response = client.get("/rotation/tracks/?time_range=medium_term")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(api.calls, [("me/top/tracks", {"limit": 10, "time_range": "medium_term"})])
        item = response.json()["items"][0]
        self.assertEqual(item["name"], "Night Drive 1")
        self.assertEqual(item["artists"], ["Ada", "Bea"])
        self.assertEqual(item["album"], "After")
        self.assertEqual(item["image"], "https://i.scdn.co/track")

    def test_an_artists_click_does_not_read_tracks(self):
        api = RecordingAPI({"items": [_artist()]})
        client = Client()
        with patch("player.features.top_rotation.views.get_spotify_api", return_value=api):
            response = client.get("/rotation/artists/?time_range=short_term")
        self.assertEqual(api.calls, [("me/top/artists", {"limit": 10, "time_range": "short_term"})])
        item = response.json()["items"][0]
        self.assertEqual(item["name"], "Ada 1")
        self.assertEqual(item["genres"], ["piano", "night"])

    def test_changing_range_refetches_only_that_list(self):
        api = RecordingAPI()
        load_top(api, "artists", "medium_term")
        load_top(api, "artists", "long_term")
        self.assertEqual(
            api.calls,
            [
                ("me/top/artists", {"limit": 10, "time_range": "medium_term"}),
                ("me/top/artists", {"limit": 10, "time_range": "long_term"}),
            ],
        )
        self.assertTrue(all(params["limit"] <= 10 for _, params in api.calls))

    def test_items_stay_at_ten_even_if_spotify_sends_more(self):
        api = RecordingAPI({"items": [_track(number) for number in range(1, 26)]})
        result = load_top(api, "tracks", "medium_term")
        self.assertEqual(len(result["items"]), 10)
        self.assertLessEqual(api.calls[0][1]["limit"], 10)

    def test_an_unknown_list_does_not_call_spotify(self):
        api = RecordingAPI()
        with self.assertRaises(TopRotationError):
            load_top(api, "albums", "medium_term")
        self.assertEqual(api.calls, [])

    def test_missing_scope_returns_needs_scope_and_the_reconnect_link(self):
        api = RecordingAPI(
            {"error": {"status": 403, "message": "Insufficient client scope"}, "items": [_track()]},
            status=403,
        )
        client = Client()
        with patch("player.features.top_rotation.views.get_spotify_api", return_value=api):
            response = client.get("/rotation/tracks/?time_range=medium_term")
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["code"], "needs_scope")
        self.assertEqual(body["link"], LOGIN_LINK)
        self.assertEqual(body["link"], "/login/?auth=1")
        self.assertNotIn("items", body)
        self.assertEqual(api.calls, [("me/top/tracks", {"limit": 10, "time_range": "medium_term"})])

    def test_artists_scope_failure_does_not_fall_through_to_tracks(self):
        api = RecordingAPI(status=403)
        client = Client()
        with patch("player.features.top_rotation.views.get_spotify_api", return_value=api):
            response = client.get("/rotation/artists/?time_range=long_term")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "needs_scope")
        self.assertEqual(response.json()["link"], "/login/?auth=1")
        self.assertEqual(api.calls, [("me/top/artists", {"limit": 10, "time_range": "long_term"})])

    def test_signed_out_click_does_not_call_spotify(self):
        api = RecordingAPI()
        client = Client()
        with patch("player.features.top_rotation.views.get_spotify_api", return_value=None):
            response = client.get("/rotation/tracks/?time_range=medium_term")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(api.calls, [])


class TopRotationScopeTests(TestCase):
    def test_scope_adds_top_read_and_keeps_existing_scopes(self):
        scopes = SPOTIFY_SCOPE.split()
        for scope in (
            "user-modify-playback-state",
            "user-read-playback-state",
            "user-read-currently-playing",
            "user-read-playback-position",
            "streaming",
            "playlist-read-private",
            "playlist-read-collaborative",
            "playlist-modify-private",
            "user-library-read",
            "user-top-read",
        ):
            self.assertIn(scope, scopes)
        self.assertEqual(scopes.count("user-top-read"), 1)

    def test_reconnect_link_reauthorizes_an_active_session(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="rotation-user",
            display_name="Rotation",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session.save()

        response = client.get("/login/?auth=1")
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertIn("accounts.spotify.com/authorize", location)
        scope = parse_qs(urlparse(location).query)["scope"][0].split()
        self.assertIn("user-top-read", scope)
        self.assertIn("playlist-modify-private", scope)
        self.assertIn("user-library-read", scope)

    def test_plain_login_keeps_an_active_session_on_the_player(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="rotation-home",
            display_name="Home",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session.save()
        response = client.get("/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response["Location"]).path, "/")

    def test_feature_source_does_not_ask_for_recommendations_or_audio_features(self):
        root = Path(__file__).resolve().parent
        source = "\n".join(
            path.read_text()
            for path in root.glob("*.py")
            if path.name != "tests.py"
        )
        lowered = source.lower()
        self.assertNotIn("recommendation", lowered)
        self.assertNotIn("audio-features", lowered)
        self.assertNotIn("audio_features", lowered)
        self.assertNotIn("me/tracks", lowered)
        self.assertNotIn("browse/", lowered)


class TopRotationPageTests(TestCase):
    def test_player_page_shows_rotation_without_reading_top_lists(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="rotation-page",
            display_name="Page",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session["use_web_player"] = True
        session.save()

        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)), \
                patch("player.spotify_api.SpotifyAPI.get") as raw_get:
            page = client.get("/")

        self.assertEqual(page.status_code, 200)
        raw_get.assert_not_called()
        body = page.content.decode()
        self.assertIn('id="tab-rotation">Rotation<', body)
        self.assertIn("loadRotation('tracks')", body)
        self.assertIn("loadRotation('artists')", body)
        self.assertIn('data-range="short_term"', body)
        self.assertIn('data-range="medium_term"', body)
        self.assertIn('data-range="long_term"', body)
        self.assertIn("if (rotationKind) loadRotation(rotationKind);", body)
        self.assertEqual(body.count("fetch('/rotation/"), 1)
        self.assertIn("fetch('/rotation/' + kind + '/?time_range='", body)
        self.assertNotIn('class="tab-content active" id="content-rotation"', body)
