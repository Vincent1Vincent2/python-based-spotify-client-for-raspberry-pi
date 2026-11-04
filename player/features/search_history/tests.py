import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from player.features.search_history.history import LIMIT, remember_query
from player.models import SpotifyAccount


class RememberQueryTests(SimpleTestCase):
    def test_newest_first(self):
        original = []
        history = remember_query(original, "alpha")
        history = remember_query(history, "beta")
        history = remember_query(history, "gamma")
        self.assertEqual(original, [])
        self.assertEqual(history, ["gamma", "beta", "alpha"])

    def test_duplicates_move_to_the_front(self):
        history = remember_query(["gamma", "beta", "alpha"], "alpha")
        self.assertEqual(history, ["alpha", "gamma", "beta"])
        self.assertEqual(remember_query(["beta", "alpha"], "beta"), ["beta", "alpha"])
        self.assertEqual(remember_query(["rock", "jazz"], "  jazz "), ["jazz", "rock"])
        full = ["8", "7", "6", "5", "4", "3", "2", "1"]
        moved = remember_query(full, "1")
        self.assertEqual(moved, ["1", "8", "7", "6", "5", "4", "3", "2"])
        self.assertEqual(len(moved), LIMIT)

    def test_ninth_drops_the_oldest(self):
        self.assertEqual(LIMIT, 8)
        history = []
        for number in range(1, 10):
            history = remember_query(history, str(number))
        self.assertEqual(history, ["9", "8", "7", "6", "5", "4", "3", "2"])
        self.assertEqual(len(history), 8)
        self.assertNotIn("1", history)

    def test_empty_strings_are_ignored(self):
        self.assertEqual(remember_query(["kept"], ""), ["kept"])
        self.assertEqual(remember_query(["kept"], "   "), ["kept"])
        self.assertEqual(remember_query(["kept"], "\n\t"), ["kept"])
        self.assertEqual(remember_query([], ""), [])
        self.assertEqual(remember_query(["kept"], None), ["kept"])
        self.assertEqual(remember_query(None, ""), [])


class _Response:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class SearchHistoryPageTests(TestCase):
    def test_player_page_includes_the_script_once(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="history-user",
            display_name="History",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session["use_web_player"] = True
        session.save()

        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=_Response({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=_Response({}, status=204)):
            page = client.get("/")

        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertEqual(body.count("/static/player/js/search-history.js"), 1)
        self.assertIn('id="searchInput"', body)
        self.assertIn('id="searchHistory"', body)
        self.assertLess(body.index('id="searchInput"'), body.index('id="searchHistory"'))
        self.assertLess(body.index('class="search-box"'), body.index('id="searchHistory"'))
        self.assertLess(body.index('id="searchHistory"'), body.index('id="searchResults"'))
        search_fn = body.index("function performSearch")
        chunk = body[search_fn:body.index("function renderSearchResults")]
        error_at = chunk.index("if (data.error)")
        return_at = chunk.index("return;", error_at)
        record_at = chunk.index("recordSearchQuery(query)")
        render_at = chunk.index("renderSearchResults(data)")
        self.assertLess(error_at, return_at)
        self.assertLess(return_at, record_at)
        self.assertLess(record_at, render_at)

    def test_script_uses_local_storage_and_the_existing_search(self):
        script = Path(settings.BASE_DIR, "player/static/player/js/search-history.js").read_text()
        self.assertEqual(script.count("spotipi.searchHistory"), 1)
        self.assertIn("searchTracks", script)
        self.assertIn("performSearch", script)
        self.assertIn("searchInput", script)
        self.assertIn("Clear", script)
        self.assertNotIn("fetch(", script)
        self.assertNotIn("/search/", script)
        self.assertNotIn("spotify.com", script.lower())
