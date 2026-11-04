import re
import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from player.features.keyboard_shortcuts.keys import (
    KEY_ACTIONS,
    action_for_key,
    is_typing_target,
)
from player.models import SpotifyAccount


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


def _shortcuts_js():
    path = Path(settings.BASE_DIR) / "player" / "static" / "player" / "js" / "shortcuts.js"
    return path.read_text(encoding="utf-8")


def _pairs(block):
    return dict(re.findall(r'"((?:[^"\\]|\\.)*)"\s*->\s*([a-z_]+)', block))


class KeyMapTests(SimpleTestCase):
    def test_letter_and_arrow_keys(self):
        self.assertEqual(action_for_key(" "), "toggle_playback")
        self.assertEqual(action_for_key("k"), "toggle_playback")
        self.assertEqual(action_for_key("K"), "toggle_playback")
        self.assertEqual(action_for_key("K", shift=True), "toggle_playback")
        self.assertEqual(action_for_key(" ", shift=True), "toggle_playback")
        self.assertEqual(action_for_key("ArrowRight"), "next_track")
        self.assertEqual(action_for_key("ArrowLeft"), "previous_track")
        self.assertEqual(action_for_key("/"), "focus_search")
        self.assertEqual(action_for_key("?"), "show_help")
        self.assertEqual(action_for_key("?", shift=True), "show_help")

    def test_shift_slash_opens_help(self):
        self.assertEqual(action_for_key("/", shift=True), "show_help")

    def test_modifier_chords_are_left_alone(self):
        self.assertIsNone(action_for_key("k", ctrl=True))
        self.assertIsNone(action_for_key("ArrowRight", alt=True))
        self.assertIsNone(action_for_key("/", shift=True, meta=True))
        self.assertIsNone(action_for_key("?", ctrl=True))

    def test_unbound_keys(self):
        self.assertIsNone(action_for_key("Enter"))
        self.assertIsNone(action_for_key("ArrowUp"))
        self.assertIsNone(action_for_key(""))
        self.assertIsNone(action_for_key(None))
        self.assertIsNone(action_for_key(1))

    def test_map_covers_each_action(self):
        self.assertEqual(
            set(KEY_ACTIONS.values()),
            {
                "toggle_playback",
                "next_track",
                "previous_track",
                "focus_search",
                "show_help",
            },
        )

    def test_typing_targets_are_inputs_textareas_and_contenteditable(self):
        self.assertTrue(is_typing_target("input"))
        self.assertTrue(is_typing_target("INPUT"))
        self.assertTrue(is_typing_target("textarea"))
        self.assertTrue(is_typing_target("div", content_editable=True))
        self.assertFalse(is_typing_target("div"))
        self.assertFalse(is_typing_target("button"))
        self.assertFalse(is_typing_target(""))
        self.assertFalse(is_typing_target(None))
        self.assertFalse(is_typing_target("div", content_editable="false"))


class ShortcutScriptTests(SimpleTestCase):
    def test_javascript_mirrors_the_python_key_map(self):
        js = _shortcuts_js()
        comment = js.split("KEY_MAP_START", 1)[1].split("KEY_MAP_END", 1)[0]
        runtime = js.split("KEY_ACTIONS = {", 1)[1].split("};", 1)[0]
        runtime_pairs = dict(
            re.findall(r'"((?:[^"\\]|\\.)*)"\s*:\s*"([a-z_]+)"', runtime)
        )
        self.assertEqual(_pairs(comment), KEY_ACTIONS)
        self.assertEqual(runtime_pairs, KEY_ACTIONS)
        self.assertIn('shift && key === "/"', js)
        self.assertIn('return "show_help"', js)

    def test_script_calls_page_functions_and_not_spotify(self):
        js = _shortcuts_js()
        self.assertIn("typeof togglePlayback === \"function\"", js)
        self.assertIn("togglePlayback()", js)
        self.assertIn("typeof nextTrack === \"function\"", js)
        self.assertIn("nextTrack()", js)
        self.assertIn("typeof previousTrack === \"function\"", js)
        self.assertIn("previousTrack()", js)
        self.assertIn('getElementById("searchInput")', js)
        self.assertIn("preventDefault", js)
        self.assertIn("isContentEditable", js)
        self.assertNotIn("fetch(", js)
        self.assertNotIn("XMLHttpRequest", js)
        self.assertNotIn("api.spotify.com", js)
        self.assertIn("Does not call Spotify", js)


class IndexShortcutsTests(TestCase):
    def test_index_html_includes_shortcuts_js_once(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="shortcut-user",
            display_name="Keys",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session["use_web_player"] = True
        session.save()

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
        self.assertEqual(body.count("player/js/shortcuts.js"), 1)
        self.assertIn(
            '<script src="/static/player/js/shortcuts.js"></script>',
            body,
        )

        login = Client().get("/login/")
        self.assertNotIn("shortcuts.js", login.content.decode())
