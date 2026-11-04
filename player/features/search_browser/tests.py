import time
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from player.features.search_browser.browse import search_page
from player.features.search_browser.query import (
    SESSION_MARKET_KEY,
    SearchBrowserError,
    build_search_query,
)
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


def _paging(type_name, items, offset=0, limit=10, total=None, next_url=None):
    key = {
        "track": "tracks",
        "album": "albums",
        "artist": "artists",
        "playlist": "playlists",
        "show": "shows",
        "episode": "episodes",
    }[type_name]
    return {
        key: {
            "items": items,
            "limit": limit,
            "offset": offset,
            "total": len(items) if total is None else total,
            "next": next_url,
        }
    }


class SearchOnlyAPI:
    """Any catalog call other than search() fails the test."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.payload)

    def __getattr__(self, name):
        def banned(*args, **kwargs):
            raise AssertionError(name)

        return banned


class QueryBuilderTests(SimpleTestCase):
    def test_query_builder_never_sends_limit_above_10(self):
        for hostile in (11, 50, 51, 100, "100", 10**6, 10**9):
            built = build_search_query("abba", "track", limit=hostile, offset=0)
            self.assertLessEqual(built["limit"], 10)
            self.assertGreaterEqual(built["limit"], 1)
            self.assertEqual(built["offset"], 0)
            self.assertNotIn(",", built["type"])

        built = build_search_query("abba", "episode", limit=10, offset=20)
        self.assertEqual(built["limit"], 10)
        self.assertEqual(built["offset"], 20)

        api = SpotifyAPI(access_token="token")
        built = build_search_query("abba", "album", limit=80, offset=15, market="gb")
        self.assertLessEqual(built["limit"], 10)
        with patch.object(api, "get", return_value=FakeResponse(_paging("album", []))) as get:
            api.search(**built)
        self.assertEqual(get.call_count, 1)
        params = get.call_args.kwargs["params"]
        self.assertLessEqual(params["limit"], 10)
        self.assertEqual(params["offset"], 15)
        self.assertEqual(params["market"], "GB")
        self.assertEqual(params["type"], "album")
        self.assertEqual(set(params), {"q", "type", "limit", "offset", "market"})

    def test_client_search_still_accepts_the_older_higher_limit(self):
        api = SpotifyAPI(access_token="token")
        with patch.object(api, "get", return_value=FakeResponse({})) as get:
            api.search(q="abba", type="track", limit=20, offset=0)
        self.assertEqual(get.call_args.kwargs["params"]["limit"], 20)
        self.assertNotIn("market", get.call_args.kwargs["params"])

    def test_type_is_one_catalog_value_and_offset_is_explicit(self):
        for type_name in ("track", "album", "artist", "playlist", "show", "episode"):
            built = build_search_query("night", type_name, limit=3, offset=30)
            self.assertEqual(built["type"], type_name)
            self.assertEqual(built["offset"], 30)
            self.assertLessEqual(built["limit"], 10)

        for bad in ("track,album", "tracks", "recommendation", "audio-features", ""):
            with self.assertRaises(SearchBrowserError):
                build_search_query("night", bad, limit=10, offset=0)

        with self.assertRaises(SearchBrowserError):
            build_search_query("night", "show", limit=10, offset=-1)

    def test_blank_market_is_omitted(self):
        built = build_search_query("night", "show", limit=10, offset=0, market="  ")
        self.assertNotIn("market", built)
        with self.assertRaises(SearchBrowserError):
            build_search_query("night", "show", limit=10, offset=0, market="USA")


class OneCallPerPageTests(SimpleTestCase):
    def test_one_search_call_per_page(self):
        payload = _paging(
            "album",
            [{
                "id": "alb1",
                "name": "Arrival",
                "artists": [{"name": "ABBA"}],
                "images": [{"url": "https://img/alb"}],
                "album_type": "album",
                "total_tracks": 12,
            }],
            total=25,
            next_url="https://api.spotify.com/v1/search?offset=10",
        )
        api = SearchOnlyAPI(payload)
        with patch("requests.request") as outbound:
            first = search_page(api, q="  abba ", type="album", limit=50, offset=0, market="us")
        outbound.assert_not_called()
        self.assertEqual(len(api.calls), 1)
        self.assertLessEqual(api.calls[0]["limit"], 10)
        self.assertEqual(api.calls[0]["offset"], 0)
        self.assertEqual(api.calls[0]["type"], "album")
        self.assertEqual(api.calls[0]["market"], "US")
        self.assertEqual(first["reads"], ["GET /search"])
        self.assertEqual(first["next_offset"], 10)
        self.assertEqual(first["items"][0]["detail_url"], "/album-detail/?id=alb1")

        second = search_page(
            api,
            q="abba",
            type="album",
            limit=999,
            offset=first["next_offset"],
            market="US",
        )
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(api.calls[1]["offset"], 10)
        self.assertLessEqual(api.calls[1]["limit"], 10)
        self.assertEqual(second["reads"], ["GET /search"])

    def test_each_type_is_a_single_search_and_detail_routes_stay_on_album_and_playlist(self):
        samples = {
            "track": {"id": "tr1", "name": "Song", "artists": [{"name": "Ada"}], "album": {"name": "LP"}},
            "album": {"id": "al1", "name": "LP", "artists": [{"name": "Ada"}]},
            "artist": {"id": "ar1", "name": "Ada"},
            "playlist": {
                "id": "pl1",
                "name": "Fiesta",
                "owner": {"display_name": "Ada"},
                "tracks": {"total": 4},
            },
            "show": {"id": "sh1", "name": "Show", "publisher": "Ada"},
            "episode": {"id": "ep1", "name": "Pilot", "show": {"name": "Show"}},
        }
        for type_name, item in samples.items():
            api = SearchOnlyAPI(_paging(type_name, [None, item], total=1))
            page = search_page(api, q="ada", type=type_name, limit=10, offset=0)
            self.assertEqual(len(api.calls), 1)
            self.assertLessEqual(api.calls[0]["limit"], 10)
            self.assertEqual(page["items"][0]["id"], item["id"])
            if type_name == "album":
                self.assertEqual(page["items"][0]["detail_url"], "/album-detail/?id=al1")
            elif type_name == "playlist":
                self.assertEqual(page["items"][0]["detail_url"], "/playlist-detail/?id=pl1")
            else:
                self.assertIsNone(page["items"][0]["detail_url"])

    def test_a_failed_search_is_still_one_call(self):
        api = SearchOnlyAPI({})
        api.search = lambda **kwargs: (_record(api, kwargs) or FakeResponse({}, status=500))
        with self.assertRaises(Exception):
            search_page(api, q="abba", type="track", limit=10, offset=0)
        self.assertEqual(len(api.calls), 1)

    def test_real_client_search_is_one_get(self):
        api = SpotifyAPI(access_token="token")
        payload = _paging(
            "playlist",
            [{
                "id": "pl9",
                "name": "Night",
                "owner": {"id": "ada"},
                "tracks": {"total": 2},
                "images": [],
            }],
            total=40,
            next_url="https://api.spotify.com/v1/search?offset=10&type=playlist",
        )
        with patch.object(api, "get", return_value=FakeResponse(payload)) as get:
            page = search_page(api, q="night", type="playlist", limit=50, offset=0)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], "search")
        self.assertLessEqual(get.call_args.kwargs["params"]["limit"], 10)
        self.assertEqual(page["items"][0]["detail_url"], "/playlist-detail/?id=pl9")
        self.assertTrue(page["has_next"])


def _record(api, kwargs):
    api.calls.append(kwargs)


class SearchBrowserViewTests(TestCase):
    def _client(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="search-user",
            display_name="Search",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session.save()
        return client

    def test_market_is_optional_and_stored_on_the_session(self):
        client = self._client()

        class PagingAPI(SearchOnlyAPI):
            def search(self, **kwargs):
                self.calls.append(kwargs)
                offset = kwargs["offset"]
                next_url = None if offset else "https://api.spotify.com/v1/search?offset=10"
                return FakeResponse(_paging(
                    "track",
                    [{"id": "tr1", "name": "Dancing Queen", "artists": [{"name": "ABBA"}]}],
                    offset=offset,
                    total=25,
                    next_url=next_url,
                ))

        api = PagingAPI({})
        with patch("player.features.search_browser.views.get_spotify_api", return_value=api):
            saved = client.get("/search-browser/?market=se")
            self.assertEqual(saved.status_code, 200)
            self.assertFalse(saved.json()["searched"])
            self.assertEqual(saved.json()["reads"], [])
            self.assertEqual(api.calls, [])
            self.assertEqual(client.session[SESSION_MARKET_KEY], "SE")

            first = client.get("/search-browser/?q=abba&type=track&offset=0&limit=40")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(len(api.calls), 1)
            self.assertEqual(api.calls[0]["market"], "SE")
            self.assertLessEqual(api.calls[0]["limit"], 10)
            self.assertEqual(api.calls[0]["offset"], 0)
            next_offset = first.json()["next_offset"]
            self.assertEqual(next_offset, first.json()["limit"])

            second = client.get(
                f"/search-browser/?q=abba&type=track&offset={next_offset}&limit=80"
            )
            self.assertEqual(len(api.calls), 2)
            self.assertEqual(api.calls[1]["offset"], next_offset)
            self.assertLessEqual(api.calls[1]["limit"], 10)
            self.assertEqual(api.calls[1]["market"], "SE")
            self.assertEqual(second.json()["reads"], ["GET /search"])

            cleared = client.get("/search-browser/?market=")
            self.assertEqual(cleared.status_code, 200)
            self.assertIsNone(cleared.json()["market"])
            self.assertNotIn(SESSION_MARKET_KEY, client.session)
            self.assertEqual(len(api.calls), 2)

    def test_bad_market_does_not_search(self):
        client = self._client()
        session = client.session
        session[SESSION_MARKET_KEY] = "US"
        session.save()
        api = SearchOnlyAPI(_paging("track", []))
        with patch("player.features.search_browser.views.get_spotify_api", return_value=api):
            response = client.get("/search-browser/?q=abba&type=track&offset=0&market=USA")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(api.calls, [])
        self.assertEqual(client.session[SESSION_MARKET_KEY], "US")

    def test_anonymous_request_does_not_search(self):
        response = Client().get("/search-browser/?q=abba&type=album&offset=0")
        self.assertEqual(response.status_code, 401)

    def test_existing_search_route_remains(self):
        self.assertEqual(reverse("search"), "/search/")
        self.assertEqual(reverse("search_browser"), "/search-browser/")

    def test_player_page_includes_the_search_panel(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id="page-user",
            display_name="Page",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session[SESSION_MARKET_KEY] = "GB"
        session["use_web_player"] = True
        session.save()

        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn(">Search+</button>", body)
        self.assertIn('id="tab-search-browser"', body)
        self.assertIn('id="content-search-browser"', body)
        self.assertIn('id="searchBrowserPanel"', body)
        self.assertIn('value="GB"', body)
        self.assertIn("/search-browser/", body)
        self.assertIn("/album-detail/", body)
        self.assertIn("/playlist-detail/", body)
        self.assertIn('id="searchInput"', body)
        self.assertIn("/search/?q=", body)
