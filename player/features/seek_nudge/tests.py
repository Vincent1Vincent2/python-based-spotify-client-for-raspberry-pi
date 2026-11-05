import time
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase

from player.features.seek_nudge.nudge import nudge_position
from player.models import SpotifyAccount
from player.tests import FakeResponse


class NudgePositionTests(SimpleTestCase):
    def test_back_from_10000_is_0(self):
        self.assertEqual(nudge_position(10000, 200000, -15000), 0)

    def test_forward_near_the_end_clamps_to_duration(self):
        duration = 200000
        self.assertEqual(nudge_position(190000, duration, 15000), duration)

    def test_middle_moves_by_15000(self):
        current = 60000
        duration = 180000
        self.assertEqual(nudge_position(current, duration, 15000), current + 15000)
        self.assertEqual(nudge_position(current, duration, -15000), current - 15000)


class SeekNudgePageTests(TestCase):
    def test_index_contains_the_two_buttons(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="nudge-user",
            display_name="Nudge",
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
        controls = body.split('<div class="controls">', 1)[1].split("</div>", 1)[0]
        self.assertIn(">−15s<", controls)
        self.assertIn(">+15s<", controls)
        self.assertIn('id="nudgeBackBtn"', controls)
        self.assertIn('id="nudgeForwardBtn"', controls)
        self.assertIn("nudgeSeek(-15000)", controls)
        self.assertIn("nudgeSeek(15000)", controls)
        self.assertLess(controls.index(">−15s<"), controls.index('id="prevBtn"'))
        self.assertLess(controls.index('id="nextBtn"'), controls.index(">+15s<"))
        self.assertIn("typeof progressCurrentMs", body)
        self.assertIn("typeof progressDurationMs", body)
        self.assertIn("function nudgeSeek", body)
        self.assertIn("/seek/?position_ms=", body)
