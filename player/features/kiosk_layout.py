from django.template.loader import render_to_string
from django.test import SimpleTestCase


class KioskLayoutTests(SimpleTestCase):
    def test_player_index_links_kiosk_css(self):
        html = render_to_string(
            "player/index.html",
            {
                "client_id": "client",
                "access_token": "token",
                "use_web_player": True,
                "devices": [],
                "accounts": [],
                "active_account": None,
                "selected_device_id": None,
            },
        )
        self.assertEqual(html.count("player/css/kiosk.css"), 1)
        self.assertIn(
            '<link rel="stylesheet" href="/static/player/css/kiosk.css">',
            html,
        )
