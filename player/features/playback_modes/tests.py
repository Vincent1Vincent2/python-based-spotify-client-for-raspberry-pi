import time
from unittest.mock import patch

from django.test import Client, TestCase

from player.models import SpotifyAccount
from player.spotify_api import SpotifyAPI


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
    def __init__(self, status=204):
        self.status = status
        self.calls = []

    def set_shuffle(self, state, device_id=None):
        self.calls.append(("shuffle", state, device_id))
        return FakeResponse({}, status=self.status)

    def set_repeat(self, state, device_id=None):
        self.calls.append(("repeat", state, device_id))
        return FakeResponse({}, status=self.status)

    def set_volume(self, volume_percent, device_id=None):
        self.calls.append(("volume", volume_percent, device_id))
        return FakeResponse({}, status=self.status)

    def get_current_playback(self, market=None, additional_types=None):
        self.calls.append(("get_current_playback", additional_types))
        return FakeResponse(self.playback, status=self.playback_status)


def _track_payload(**overrides):
    payload = {
        "device": {
            "id": "dev-1",
            "name": "Pi",
            "type": "Speaker",
            "volume_percent": 37,
            "is_active": True,
        },
        "shuffle_state": True,
        "repeat_state": "context",
        "progress_ms": 1200,
        "is_playing": True,
        "currently_playing_type": "track",
        "context": {"uri": "spotify:playlist:abc"},
        "item": {
            "type": "track",
            "id": "track1",
            "uri": "spotify:track:track1",
            "name": "Lonely Road",
            "duration_ms": 180000,
            "artists": [{"name": "Ada"}],
            "album": {
                "name": "Album",
                "images": [{"url": "https://example.com/cover.jpg"}],
            },
        },
    }
    payload.update(overrides)
    return payload


class SpotifyModeMethodTests(TestCase):
    def test_shuffle_repeat_and_volume_are_one_put_each(self):
        api = SpotifyAPI(access_token="token")
        recorded = []

        def _request(method, endpoint, **kwargs):
            recorded.append((method, endpoint, kwargs.get("params")))
            return FakeResponse({}, 204)

        api._request = _request
        api.set_shuffle(True)
        api.set_shuffle(False, device_id="dev")
        api.set_repeat("off")
        api.set_repeat("context", device_id="dev")
        api.set_repeat("track")
        api.set_volume(0)
        api.set_volume(100, device_id="dev")

        self.assertEqual(recorded, [
            ("PUT", "me/player/shuffle", {"state": "true"}),
            ("PUT", "me/player/shuffle", {"state": "false", "device_id": "dev"}),
            ("PUT", "me/player/repeat", {"state": "off"}),
            ("PUT", "me/player/repeat", {"state": "context", "device_id": "dev"}),
            ("PUT", "me/player/repeat", {"state": "track"}),
            ("PUT", "me/player/volume", {"volume_percent": 0}),
            ("PUT", "me/player/volume", {"volume_percent": 100, "device_id": "dev"}),
        ])


class PlaybackModeViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.api = FakeAPI()

    def _patch(self):
        return patch(
            "player.features.playback_modes.views.get_spotify_api",
            return_value=self.api,
        )

    def _select_device(self, device_id="speaker-9"):
        session = self.client.session
        session["use_web_player"] = False
        session["selected_device_id"] = device_id
        session.save()

    def test_modes_require_a_login(self):
        self.assertEqual(self.client.post("/shuffle/?state=true").status_code, 401)
        self.assertEqual(self.client.post("/repeat/?state=off").status_code, 401)
        self.assertEqual(self.client.post("/volume/?volume_percent=10").status_code, 401)

    def test_shuffle_sends_true_or_false_to_the_selected_device(self):
        self._select_device()
        with self._patch():
            on = self.client.post("/shuffle/?state=true")
            off = self.client.post("/shuffle/?state=false")
        self.assertEqual(on.status_code, 200)
        self.assertEqual(on.json(), {"status": "shuffle", "state": True})
        self.assertEqual(off.json()["state"], False)
        self.assertEqual(self.api.calls, [
            ("shuffle", True, "speaker-9"),
            ("shuffle", False, "speaker-9"),
        ])

    def test_shuffle_on_the_web_player_omits_the_device(self):
        session = self.client.session
        session["use_web_player"] = True
        session["selected_device_id"] = "speaker-9"
        session.save()
        with self._patch():
            response = self.client.post("/shuffle/?state=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.api.calls, [("shuffle", True, None)])

    def test_shuffle_rejects_anything_other_than_true_or_false(self):
        with self._patch():
            response = self.client.post("/shuffle/?state=yes")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.api.calls, [])

    def test_repeat_accepts_off_context_and_track(self):
        self._select_device("dev-2")
        with self._patch():
            responses = [
                self.client.post(f"/repeat/?state={state}")
                for state in ("off", "context", "track")
            ]
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(self.api.calls, [
            ("repeat", "off", "dev-2"),
            ("repeat", "context", "dev-2"),
            ("repeat", "track", "dev-2"),
        ])

    def test_repeat_rejects_an_unknown_state(self):
        with self._patch():
            response = self.client.post("/repeat/?state=all")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.api.calls, [])

    def test_volume_accepts_the_ends_of_the_range(self):
        self._select_device()
        with self._patch():
            low = self.client.post("/volume/?volume_percent=0")
            high = self.client.post("/volume/?volume_percent=100")
        self.assertEqual(low.status_code, 200)
        self.assertEqual(low.json(), {"status": "volume", "volume_percent": 0})
        self.assertEqual(high.json()["volume_percent"], 100)
        self.assertEqual(self.api.calls, [
            ("volume", 0, "speaker-9"),
            ("volume", 100, "speaker-9"),
        ])

    def test_volume_rejects_out_of_range_and_blank_values(self):
        with self._patch():
            missing = self.client.post("/volume/")
            low = self.client.post("/volume/?volume_percent=-1")
            high = self.client.post("/volume/?volume_percent=101")
            text = self.client.post("/volume/?volume_percent=loud")
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(low.status_code, 400)
        self.assertEqual(high.status_code, 400)
        self.assertEqual(text.status_code, 400)
        self.assertEqual(self.api.calls, [])

    def test_spotify_errors_stay_on_the_player(self):
        self.api.status = 403
        with self._patch():
            response = self.client.post("/volume/?volume_percent=40")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "playback_error")
        self.assertEqual(self.api.calls, [("volume", 40, None)])


class CurrentPlaybackModeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.api = FakeAPI()

    def _get(self):
        with patch("player.views.get_spotify_api", return_value=self.api):
            return self.client.get("/current-playback/")

    def test_track_playback_keeps_its_fields_and_adds_the_three_modes(self):
        self.api.playback = _track_payload()
        self.api.playback_status = 200
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "is_playing": True,
            "track": {
                "id": "track1",
                "uri": "spotify:track:track1",
                "name": "Lonely Road",
                "artists": ["Ada"],
                "album": "Album",
                "image": "https://example.com/cover.jpg",
                "duration_ms": 180000,
                "progress_ms": 1200,
                "type": "track",
            },
            "type": "track",
            "shuffle_state": True,
            "repeat_state": "context",
            "device": {
                "id": "dev-1",
                "name": "Pi",
                "type": "Speaker",
                "volume_percent": 37,
            },
        })
        self.assertEqual(self.api.calls, [("get_current_playback", "track,episode")])

    def test_episode_playback_exposes_the_same_mode_fields(self):
        self.api.playback = {
            "device": {"id": "dev-1", "name": "Pi", "type": "Speaker", "volume_percent": 12},
            "shuffle_state": False,
            "repeat_state": "track",
            "progress_ms": 5,
            "is_playing": False,
            "currently_playing_type": "episode",
            "item": {
                "type": "episode",
                "id": "ep1",
                "name": "Show notes",
                "description": "hello",
                "duration_ms": 60000,
                "images": [{"url": "https://example.com/ep.jpg"}],
                "show": {"name": "Night"},
            },
        }
        self.api.playback_status = 200
        body = self._get().json()
        self.assertEqual(body["type"], "episode")
        self.assertEqual(body["track"]["name"], "Show notes")
        self.assertEqual(body["track"]["show"], "Night")
        self.assertEqual(body["shuffle_state"], False)
        self.assertEqual(body["repeat_state"], "track")
        self.assertEqual(body["device"]["volume_percent"], 12)
        self.assertEqual(set(body["device"]), {"id", "name", "type", "volume_percent"})

    def test_paused_device_keeps_a_zero_volume(self):
        self.api.playback = {
            "device": {"id": "dev-1", "name": "Pi", "type": "Speaker", "volume_percent": 0},
            "shuffle_state": False,
            "repeat_state": "off",
            "progress_ms": 0,
            "is_playing": False,
            "item": None,
        }
        self.api.playback_status = 200
        body = self._get().json()
        self.assertEqual(body["track"], None)
        self.assertEqual(body["type"], None)
        self.assertEqual(body["is_playing"], False)
        self.assertEqual(body["shuffle_state"], False)
        self.assertEqual(body["repeat_state"], "off")
        self.assertEqual(body["device"]["volume_percent"], 0)

    def test_nothing_playing_stays_unchanged(self):
        self.api.playback = None
        self.api.playback_status = 204
        self.api.get_current_playback = lambda market=None, additional_types=None: FakeResponse({}, status=204)
        body = self._get().json()
        self.assertEqual(body, {
            "is_playing": False,
            "track": None,
            "type": None,
            "device": None,
        })

    def test_missing_volume_is_passed_through(self):
        self.api.playback = _track_payload()
        del self.api.playback["device"]["volume_percent"]
        self.api.playback["shuffle_state"] = False
        self.api.playback["repeat_state"] = "off"
        self.api.playback_status = 200
        body = self._get().json()
        self.assertIsNone(body["device"]["volume_percent"])
        self.assertIn("volume_percent", body["device"])
        self.assertEqual(body["track"]["name"], "Lonely Road")


class PlaybackModePageTests(TestCase):
    def test_player_controls_include_shuffle_repeat_and_volume(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="mode-page",
            display_name="Mode",
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
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="shuffleBtn"', body)
        self.assertIn(">Shuffle</button>", body)
        self.assertIn('id="repeatBtn"', body)
        self.assertIn(">Repeat</button>", body)
        self.assertIn('data-cycle="off context track"', body)
        self.assertIn('id="volumeRange"', body)
        self.assertIn('min="0"', body)
        self.assertIn('max="100"', body)
        self.assertIn("/shuffle/?state=", body)
        self.assertIn("/repeat/?state=", body)
        self.assertIn("/volume/?volume_percent=", body)
        self.assertIn("function cycleRepeat()", body)
        self.assertIn("off context track", body)
