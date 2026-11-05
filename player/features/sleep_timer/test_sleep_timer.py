from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from player.features.sleep_timer.options import (
    END_OF_TRACK,
    END_OF_TRACK_LABEL,
    minute_choices,
    timer_options,
)


class SleepTimerOptionsTests(SimpleTestCase):
    def test_minute_choices_are_fifteen_thirty_forty_five_and_sixty(self):
        self.assertEqual(minute_choices(), (15, 30, 45, 60))

    def test_timer_options_follow_the_minute_choices_then_end_of_track(self):
        options = timer_options()
        self.assertEqual(
            [option["minutes"] for option in options if option["kind"] == "minutes"],
            list(minute_choices()),
        )
        self.assertEqual(
            [option["label"] for option in options if option["kind"] == "minutes"],
            [f"{minutes} minutes" for minutes in minute_choices()],
        )
        self.assertEqual(options[-1]["kind"], END_OF_TRACK)
        self.assertEqual(options[-1]["label"], END_OF_TRACK_LABEL)
        self.assertIsNone(options[-1]["minutes"])
        self.assertEqual(len(options), len(minute_choices()) + 1)


class SleepTimerTemplateTests(SimpleTestCase):
    def test_index_includes_timer_root(self):
        index_path = Path(settings.BASE_DIR) / "player" / "templates" / "player" / "index.html"
        source = index_path.read_text()
        self.assertIn('{% include "player/features/sleep_timer/timer.html" %}', source)
        self.assertEqual(source.count("sleep_timer"), 1)

        html = render_to_string("player/index.html", {
            "client_id": "client",
            "access_token": "token",
            "devices": [],
            "use_web_player": True,
            "selected_device_id": None,
        })
        self.assertIn('id="sleep-timer"', html)
        self.assertIn('id="sleep-timer-remaining"', html)
        self.assertIn('id="sleep-timer-cancel"', html)
        self.assertIn(">Cancel<", html)
        self.assertIn('data-sleep-end="end"', html)
        self.assertIn(END_OF_TRACK_LABEL, html)
        for minutes in minute_choices():
            self.assertIn(f'data-sleep-minutes="{minutes}"', html)
            self.assertIn(f"{minutes} minutes", html)
        self.assertIn("/static/player/features/sleep_timer/sleep_timer.js", html)
