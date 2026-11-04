import json
import time
from unittest.mock import patch

from django.test import Client, TestCase

from player.features.track_actions.actions import add_track_to_playlist, save_track, save_uri
from player.models import SpotifyAccount
from player.views import SPOTIFY_SCOPE


class _Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class RecordingAPI:
    def __init__(self):
        self.puts = []
        self.adds = []

    def put(self, endpoint, **kwargs):
        self.puts.append((endpoint, kwargs))
        return _Response(200)

    def add_playlist_items(self, playlist_id, uris):
        self.adds.append((playlist_id, list(uris)))
        return _Response(201)


class SaveUriTests(TestCase):
    def test_save_uri_builder(self):
        self.assertEqual(save_uri("abc123"), "spotify:track:abc123")
        self.assertEqual(save_uri("  spotify:track:abc123  "), "spotify:track:abc123")

        api = RecordingAPI()
        saved = save_track(api, "abc123")
        self.assertEqual(saved["uri"], "spotify:track:abc123")
        self.assertEqual(len(api.puts), 1)
        endpoint, kwargs = api.puts[0]
        self.assertEqual(endpoint, "me/library")
        self.assertEqual(kwargs["params"]["uris"], "spotify:track:abc123")

    def test_save_endpoint_puts_library_uri_once(self):
        api = RecordingAPI()
        with patch("player.features.track_actions.views.get_spotify_api", return_value=api):
            response = self.client.post("/track-actions/save/?id=abc123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["uri"], "spotify:track:abc123")
        self.assertEqual(len(api.puts), 1)
        self.assertEqual(api.puts[0][1]["params"]["uris"], "spotify:track:abc123")


class AddItemsCallCountTests(TestCase):
    def test_add_items_call_count_is_one(self):
        api = RecordingAPI()
        add_track_to_playlist(api, "pl1", "spotify:track:abc123")
        self.assertEqual(len(api.adds), 1)
        self.assertEqual(api.adds[0], ("pl1", ["spotify:track:abc123"]))

    def test_playlist_endpoint_calls_add_items_once(self):
        api = RecordingAPI()
        with patch("player.features.track_actions.views.get_spotify_api", return_value=api):
            response = self.client.post(
                "/track-actions/playlist/",
                data=json.dumps({"playlist_id": "pl1", "uri": "spotify:track:abc123"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "added")
        self.assertEqual(len(api.adds), 1)
        self.assertEqual(api.adds[0], ("pl1", ["spotify:track:abc123"]))

    def test_missing_uri_does_not_call_add_items(self):
        api = RecordingAPI()
        with patch("player.features.track_actions.views.get_spotify_api", return_value=api):
            response = self.client.post(
                "/track-actions/playlist/",
                data=json.dumps({"playlist_id": "pl1"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(api.adds, [])


class TrackActionScopeTests(TestCase):
    def test_scopes_keep_current_and_add_library_modify(self):
        self.assertEqual(
            SPOTIFY_SCOPE.split(),
            [
                "user-modify-playback-state",
                "user-read-playback-state",
                "user-read-currently-playing",
                "user-read-playback-position",
                "streaming",
                "playlist-read-private",
                "playlist-read-collaborative",
                "playlist-modify-private",
                "user-library-read",
                "user-library-modify",
            ],
        )


class TrackActionsPageTests(TestCase):
    def test_menu_keeps_play_and_queue_and_adds_actions(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="track-actions-user",
            display_name="Tracks",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session["use_web_player"] = True
        session.save()

        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=_Response(payload={"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=_Response(status=204)):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("Play Now", body)
        self.assertIn("Add to Queue", body)
        self.assertIn('data-action="save"', body)
        self.assertIn("Add to playlist", body)
        self.assertIn("Open album", body)
        self.assertIn('id="track-actions-album"', body)
        self.assertIn("/album-detail/?id=", body)
        self.assertIn("/playlists/", body)
