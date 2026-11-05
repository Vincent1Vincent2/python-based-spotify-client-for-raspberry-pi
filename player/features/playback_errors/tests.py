from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase

from player.features.playback_errors.message import (
    NEEDS_SCOPE_MESSAGE,
    playback_error_message,
)


class PlaybackErrorMessageTests(SimpleTestCase):
    def test_error_string(self):
        self.assertEqual(
            playback_error_message({"error": "No device selected"}),
            "No device selected",
        )
        self.assertEqual(
            playback_error_message({
                "error": {"status": 404, "message": "No active device"},
            }),
            "No active device",
        )

    def test_missing_error(self):
        self.assertEqual(playback_error_message({"status": "playing"}), "")
        self.assertEqual(playback_error_message({}), "")
        self.assertEqual(playback_error_message(None), "")

    def test_needs_scope(self):
        self.assertEqual(
            playback_error_message({"code": "needs_scope"}),
            NEEDS_SCOPE_MESSAGE,
        )
        self.assertEqual(
            playback_error_message({
                "code": "needs_scope",
                "error": "Premium required",
            }),
            "Premium required",
        )


class _Response:
    def __init__(self, payload=None, status=204):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload


class _API:
    def __init__(self, payload=None, status=204):
        self.payload = {} if payload is None else payload
        self.status = status

    def transfer_playback(self, device_id=None, force_play=False):
        return _Response({}, 204)

    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        return _Response(self.payload, self.status)

    def pause_playback(self, device_id=None):
        return _Response(self.payload, self.status)

    def next_track(self, device_id=None):
        return _Response(self.payload, self.status)

    def previous_track(self, device_id=None):
        return _Response(self.payload, self.status)


class PlaybackCommandViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        session = self.client.session
        session["use_web_player"] = False
        session["selected_device_id"] = "device-1"
        session.save()

    def _post(self, path, api):
        with patch("player.views.get_spotify_client", return_value=api):
            return self.client.post(path)

    def test_pause_next_and_previous_surface_the_spotify_error(self):
        payload = {"error": {"status": 404, "message": "Device not found"}}
        for path in ("/pause/", "/next/", "/previous/"):
            response = self._post(path, _API(payload, 404))
            self.assertEqual(response.status_code, 502, path)
            self.assertEqual(response.json(), {
                "error": "Device not found",
                "code": "playback_error",
            })

    def test_play_surfaces_the_spotify_error_without_a_success_status(self):
        response = self._post("/play/", _API({
            "error": "Restriction violated",
            "code": "needs_scope",
        }, 403))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {
            "error": "Restriction violated",
            "code": "needs_scope",
        })

    def test_pause_success_still_reports_paused(self):
        response = self._post("/pause/", _API({}, 204))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "paused"})
