import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from django.test import Client, TestCase

from player.feel import (
    BATCH_SIZE,
    QUERY_CHAR_LIMIT,
    FeelError,
    build_query,
    collect_corpus,
    feel_name,
    is_generated_playlist_name,
    order_for_radio,
    refill_from_search,
    score_track,
    similarity,
)
from player.feel_radio import advance_feel_radio, start_feel_radio
from player.models import FeelRadio, SpotifyAccount


def _track(number, name, artist="Ada"):
    return {
        "id": f"id{number}",
        "uri": f"spotify:track:{number}",
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": "Album"},
    }


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
    def __init__(self, playlists, playlist_tracks, saved_tracks=None, search_tracks=None):
        self.playlists = playlists
        self.playlist_tracks = playlist_tracks
        self.saved_tracks = saved_tracks or []
        self.search_tracks = search_tracks or []
        self.calls = []
        self.created = []
        self.added = []
        self._next_id = 1

    def get_user_playlists(self, limit=50, offset=0):
        self.calls.append("playlists")
        return FakeResponse({"items": self.playlists})

    def get_playlist_tracks(self, playlist_id, limit=50, offset=0):
        self.calls.append(("playlist_tracks", playlist_id, limit))
        return FakeResponse({"items": [{"track": track} for track in self.playlist_tracks]})

    def get_user_saved_tracks(self, limit=50, offset=0):
        self.calls.append(("saved_tracks", limit))
        return FakeResponse({"items": [{"track": track} for track in self.saved_tracks]})

    def search(self, q, type="track", limit=10, offset=0):
        self.calls.append(("search", q, limit))
        return FakeResponse({"tracks": {"items": self.search_tracks}})

    def create_playlist(self, name, description="", public=False):
        self.calls.append(("create", name, public))
        playlist_id = f"pl{self._next_id}"
        self._next_id += 1
        self.created.append({"id": playlist_id, "name": name, "description": description})
        return FakeResponse({"id": playlist_id}, status=201)

    def add_playlist_items(self, playlist_id, uris):
        self.calls.append(("add", playlist_id, len(uris)))
        self.added.append({"id": playlist_id, "uris": list(uris)})
        return FakeResponse({}, status=201)

    def set_shuffle(self, state, device_id=None):
        self.calls.append(("shuffle", state))
        return FakeResponse({}, status=204)

    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        self.calls.append(("play", context_uri, offset))
        return FakeResponse({}, status=204)


class FeelMatchingTests(TestCase):
    def test_feel_name_ignores_click_order(self):
        self.assertEqual(feel_name(["mad", "sad"]), "Sad Mad")
        self.assertEqual(feel_name(["sad", "mad", "happy"]), "Sad Happy Mad")

    def test_unknown_emotion_is_rejected(self):
        with self.assertRaises(FeelError):
            feel_name(["sleepy"])

    def test_combination_ranks_above_a_single_emotion(self):
        both = {"uri": "spotify:track:1", "name": "angry tears", "artists": [], "album": ""}
        only = {"uri": "spotify:track:2", "name": "angry people", "artists": [], "album": ""}
        self.assertGreater(
            score_track(both, ["sad", "mad"]),
            score_track(only, ["sad", "mad"]),
        )

    def test_mad_does_not_match_inside_another_word(self):
        track = {"uri": "spotify:track:3", "name": "made of gold", "artists": [], "album": ""}
        self.assertEqual(score_track(track, ["mad"]), 0)

    def test_query_leads_with_the_song_that_is_ending_and_stays_short(self):
        query = build_query(
            ["sad", "mad"],
            {"name": "Lonely Road", "artists": ["A" * 90], "uri": "spotify:track:9"},
        )
        self.assertTrue(query.startswith("lonely"))
        self.assertLessEqual(len(query), QUERY_CHAR_LIMIT)
        self.assertNotIn("A" * 90, query)
        self.assertIn("sad", query)

    def test_same_artist_is_closer_than_an_unrelated_title(self):
        left = {"name": "blue", "artists": ["Ada"]}
        same = {"name": "other", "artists": ["Ada"]}
        other = {"name": "other", "artists": ["Bea"]}
        self.assertGreater(similarity(left, same), similarity(left, other))

    def test_generated_playlists_are_recognized(self):
        self.assertTrue(is_generated_playlist_name("Sad Mad Radio"))
        self.assertTrue(is_generated_playlist_name("Sad Mad 01"))
        self.assertFalse(is_generated_playlist_name("Sad Songs"))

    def test_collect_uses_two_reads_and_the_matching_playlist(self):
        reads = []

        def read_playlists():
            reads.append("playlists")
            return {"items": [
                {"id": "own", "name": "Sad Radio", "tracks": {"total": 10}},
                {"id": "lib", "name": "Sad Songs", "tracks": {"total": 12}},
            ]}

        def read_playlist_tracks(playlist_id):
            reads.append(playlist_id)
            return {"items": [{"track": _track(1, "tears on the floor")}]}

        def read_saved_tracks():
            reads.append("saved")
            return {"items": []}

        tracks, source, labels = collect_corpus(
            ["sad"], read_playlists, read_playlist_tracks, read_saved_tracks,
        )
        self.assertEqual(reads, ["playlists", "lib"])
        self.assertEqual(source["name"], "Sad Songs")
        self.assertEqual(len(labels), 2)
        self.assertEqual(tracks[0]["name"], "tears on the floor")

    def test_collect_falls_back_to_saved_songs_in_the_second_read(self):
        reads = []

        def read_playlists():
            reads.append("playlists")
            return {"items": [{"id": "road", "name": "Road Trip", "tracks": {"total": 4}}]}

        def read_playlist_tracks(playlist_id):
            reads.append(playlist_id)
            return {"items": []}

        def read_saved_tracks():
            reads.append("saved")
            return {"items": [{"track": _track(2, "sunshine dance")}]}

        _tracks, source, _labels = collect_corpus(
            ["happy"], read_playlists, read_playlist_tracks, read_saved_tracks,
        )
        self.assertEqual(reads, ["playlists", "saved"])
        self.assertEqual(source["kind"], "saved_tracks")

    def test_refill_searches_once_and_skips_songs_already_used(self):
        calls = []

        def search(query):
            calls.append(query)
            return {"tracks": {"items": [
                _track(1, "lonely hearts"),
                _track(2, "lonely again"),
            ]}}

        found, query = refill_from_search(
            ["sad"],
            {"name": "Lonely Road", "artists": ["Ada"], "uri": "spotify:track:seed"},
            search,
            {"spotify:track:1"},
        )
        self.assertEqual(calls, [query])
        self.assertEqual([track["uri"] for track in found], ["spotify:track:2"])

    def test_chain_starts_on_the_strongest_feel(self):
        tracks = [
            {"uri": "spotify:track:a", "name": "parking lot", "artists": ["Ada"], "album": ""},
            {"uri": "spotify:track:b", "name": "lonely tears", "artists": ["Bea"], "album": ""},
        ]
        ordered = order_for_radio(tracks, ["sad"])
        self.assertEqual(ordered[0]["uri"], "spotify:track:b")


class FeelRadioTests(TestCase):
    def setUp(self):
        self.account = SpotifyAccount.objects.create(
            spotify_user_id="feel-user",
            display_name="Feel",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=0,
        )

    def _library(self, count=40):
        tracks = [_track(index, f"lonely tears {index}") for index in range(count)]
        playlists = [{"id": "lib", "name": "Sad Songs", "tracks": {"total": count}}]
        return FakeAPI(playlists, tracks)

    def test_start_reads_twice_and_saves_a_30_song_playlist(self):
        api = self._library()
        result = start_feel_radio(api, self.account, ["mad", "sad"], "device-1", True)
        self.assertEqual(result["feel_name"], "Sad Mad")
        self.assertEqual(result["radio_name"], "Sad Mad Radio")
        self.assertEqual(len(result["tracks"]), BATCH_SIZE)
        self.assertEqual(result["reads"], ["GET /me/playlists", "GET /playlists/lib/tracks"])
        self.assertNotIn("search", [call[0] for call in api.calls if isinstance(call, tuple)])
        self.assertEqual(api.calls[0], "playlists")
        self.assertEqual(api.calls[1][0], "playlist_tracks")
        self.assertEqual(api.calls[1][2], 50)
        names = [item["name"] for item in api.created]
        self.assertEqual(names, ["Sad Mad Radio", "Sad Mad 01"])
        self.assertEqual(len(api.added[0]["uris"]), 30)
        self.assertEqual(len(api.added[1]["uris"]), 30)
        self.assertTrue(all(not item["name"].endswith("public") for item in api.created))
        self.assertFalse(api.created[0]["name"] == "")
        radio = FeelRadio.objects.get(account=self.account)
        self.assertEqual(radio.counters["Sad Mad"], 1)
        self.assertEqual(len(radio.pool), 10)
        self.assertTrue(radio.active)

    def test_second_start_keeps_the_number_going(self):
        start_feel_radio(self._library(), self.account, ["sad"], "device-1", True)
        api = self._library()
        start_feel_radio(api, self.account, ["sad"], "device-1", True)
        self.assertIn("Sad 02", [item["name"] for item in api.created])

    def test_advance_with_a_full_pile_does_not_search(self):
        start_feel_radio(self._library(), self.account, ["sad"], "device-1", True)
        radio = FeelRadio.objects.get(account=self.account)
        radio.pool = [
            {
                "uri": f"spotify:track:pool{index}",
                "id": f"pool{index}",
                "name": f"lonely pool {index}",
                "artists": ["Ada"],
                "album": "Album",
            }
            for index in range(BATCH_SIZE)
        ]
        radio.save(update_fields=["pool"])
        api = FakeAPI([], [])
        result = advance_feel_radio(api, self.account, "device-1", radio.tail_uri, 5000, False)
        self.assertTrue(result["extended"])
        self.assertNotIn("search", [call[0] for call in api.calls if isinstance(call, tuple)])
        self.assertEqual(result["reads"], [])
        self.assertIn("Sad 02", [snap["name"] for snap in result["snapshots"]])

    def test_advance_before_the_end_does_not_call_spotify(self):
        start_feel_radio(self._library(), self.account, ["sad"], "device-1", True)
        radio = FeelRadio.objects.get(account=self.account)
        api = FakeAPI([], [])
        result = advance_feel_radio(api, self.account, "device-1", radio.tail_uri, 90000, False)
        self.assertFalse(result["extended"])
        self.assertEqual(api.calls, [])

    def test_a_gap_after_the_tail_extend_does_not_add_again(self):
        start_feel_radio(self._library(), self.account, ["sad"], "device-1", True)
        radio = FeelRadio.objects.get(account=self.account)
        radio.last_extend_uri = radio.tail_uri
        radio.save(update_fields=["last_extend_uri"])
        api = FakeAPI([], [])
        result = advance_feel_radio(api, self.account, "device-1", "", None, True)
        self.assertFalse(result["extended"])
        self.assertEqual(api.calls, [])

    def test_a_short_pile_costs_one_search(self):
        api = self._library(count=30)
        start_feel_radio(api, self.account, ["sad"], "device-1", True)
        radio = FeelRadio.objects.get(account=self.account)
        self.assertEqual(radio.pool, [])
        search_api = FakeAPI([], [], search_tracks=[_track(100 + i, f"lonely encore {i}") for i in range(10)])
        result = advance_feel_radio(search_api, self.account, "device-1", radio.tail_uri, 1000, False)
        self.assertTrue(result["extended"])
        searches = [call for call in search_api.calls if isinstance(call, tuple) and call[0] == "search"]
        self.assertEqual(len(searches), 1)
        self.assertEqual(searches[0][2], 10)
        self.assertLessEqual(len(searches[0][1]), 100)
        self.assertEqual(result["reads"], ["GET /search"])

    def test_private_playlist_create_uses_the_body_flag(self):
        api = self._library()
        start_feel_radio(api, self.account, ["sad"], "device-1", True)
        self.assertTrue(all(call[2] is False for call in api.calls if isinstance(call, tuple) and call[0] == "create"))
        raw = json.dumps(api.created)
        self.assertNotIn('"public": true', raw)


class FeelPageTests(TestCase):
    def test_player_page_shows_the_feel_tab_without_calling_spotify_again(self):
        import time
        from unittest.mock import patch

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
        session["use_web_player"] = True
        session.save()

        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("Feel radio", body)
        self.assertIn('data-emotion="sad"', body)
        self.assertIn('data-emotion="happy"', body)
        self.assertIn('data-emotion="mad"', body)
        self.assertIn("Keep going after the last song", body)

        status = client.get("/feel/status/")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["active"])



FORBIDDEN_DISCOVER_URLS = (
    "recommendations",
    "browse/categories",
    "featured-playlists",
    "new-releases",
)


class FakeDiscoverAPI:
    """Records each Spotify GET url issued while Discover is loading."""

    def __init__(self, recent=None, search=None, saved=None):
        self.recent = {"items": []} if recent is None else recent
        self.search_payload = {} if search is None else search
        self.saved = {"items": []} if saved is None else saved
        self.urls = []
        self.calls = []

    def get(self, endpoint, params=None, **kwargs):
        params = dict(params or {})
        query = urlencode(params)
        url = "/" + endpoint.lstrip("/")
        if query:
            url = f"{url}?{query}"
        self.urls.append(url)
        self.calls.append((endpoint, params))
        if endpoint == "me/player/recently-played":
            return FakeResponse(self.recent)
        if endpoint == "search":
            return FakeResponse(self.search_payload)
        if endpoint == "me/tracks":
            return FakeResponse(self.saved)
        return FakeResponse({"error": endpoint}, status=500)


def _catalog_track(track_id, name, artist, album_id, album_name, duration_ms=180000):
    artists = [{"id": "artist", "name": artist}] if artist else []
    return {
        "id": track_id,
        "name": name,
        "uri": f"spotify:track:{track_id}",
        "duration_ms": duration_ms,
        "preview_url": None,
        "type": "track",
        "artists": artists,
        "album": {
            "id": album_id,
            "name": album_name,
            "type": "album",
            "release_date": "2020-05-01",
            "total_tracks": 10,
            "images": [{"url": f"https://i.scdn.co/image/{album_id}", "width": 300, "height": 300}],
            "artists": list(artists),
            },
    }


class DiscoverTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _fetch(self, api):
        with patch("player.views.get_spotify_client", return_value=api):
            return self.client.get("/discover/")

    def _assert_two_reads(self, api):
        self.assertLessEqual(len(api.urls), 2)
        self.assertGreaterEqual(len(api.urls), 1)
        blob = "\n".join(api.urls)
        for banned in FORBIDDEN_DISCOVER_URLS:
            self.assertNotIn(banned, blob)
        for endpoint, _params in api.calls:
            for banned in FORBIDDEN_DISCOVER_URLS:
                self.assertNotIn(banned, endpoint)

    def test_scope_adds_recently_played_and_keeps_current_scopes(self):
        from player.views import SPOTIFY_SCOPE

        scopes = SPOTIFY_SCOPE.split()
        expected = [
            "user-modify-playback-state",
            "user-read-playback-state",
            "user-read-currently-playing",
            "user-read-playback-position",
            "streaming",
            "playlist-read-private",
            "playlist-read-collaborative",
            "playlist-modify-private",
            "user-library-read",
            "user-read-recently-played",
        ]
        for scope in expected:
            self.assertIn(scope, scopes)
        self.assertEqual(scopes.count("user-read-recently-played"), 1)
        self.assertEqual(scopes.count("playlist-modify-private"), 1)

    def test_recent_plays_search_once_from_the_top_artist(self):
        ada = _catalog_track("t1", "Blue Moon", "Ada", "al-blue", "Blue Album")
        ada_again = _catalog_track("t2", "Gold Dust", "Ada", "al-gold", "Gold Album")
        bea = _catalog_track("t3", "Other Place", "Bea", "al-bea", "Bea Album")
        found_track = _catalog_track("t9", "New Coast", "Cora", "al-north", "North", duration_ms=200000)
        found_album = {
            "id": "al-extra",
            "name": "Extra",
            "type": "album",
            "release_date": "2021-01-02",
            "total_tracks": 8,
            "images": [{"url": "https://i.scdn.co/image/extra"}],
            "artists": [{"name": "Cora"}],
        }
        api = FakeDiscoverAPI(
            recent={"items": [
                {"track": ada, "played_at": "2026-01-03T00:00:00Z"},
                {"track": ada_again, "played_at": "2026-01-02T00:00:00Z"},
                {"track": bea, "played_at": "2026-01-01T00:00:00Z"},
                {"track": None, "played_at": "2026-01-01T00:00:00Z"},
            ]},
            search={
                "tracks": {"items": [found_track, None]},
                "albums": {"items": [found_album]},
                "playlists": {"items": []},
            },
        )

        response = self._fetch(api)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(api.urls), 2)
        self._assert_two_reads(api)
        self.assertEqual(api.calls[0], ("me/player/recently-played", {"limit": 10}))
        self.assertEqual(api.calls[1][0], "search")
        self.assertEqual(api.calls[1][1]["limit"], 10)
        query = api.calls[1][1]["q"]
        self.assertTrue(query.startswith("Ada"))
        self.assertIn("blue", query.lower())
        self.assertIn(" OR ", query)
        self.assertNotIn("Bea", query)
        self.assertLessEqual(len(query), 100)
        self.assertNotIn("search", api.urls[0])
        self.assertNotIn("me/tracks", api.urls[1])
        body = response.json()
        self.assertEqual(set(body), {"playlists", "albums", "tracks"})
        self.assertEqual(body["playlists"], [])
        self.assertEqual(body["tracks"][0]["name"], "New Coast")
        self.assertEqual(body["tracks"][0]["artists"], ["Cora"])
        self.assertEqual(body["tracks"][0]["album"], "North")
        self.assertEqual(body["tracks"][0]["duration_ms"], 200000)
        self.assertEqual(body["tracks"][0]["image"], "https://i.scdn.co/image/al-north")
        self.assertEqual(body["tracks"][0]["id"], "t9")
        album_ids = [album["id"] for album in body["albums"]]
        self.assertEqual(album_ids[0], "al-extra")
        self.assertIn("al-north", album_ids)
        extra = body["albums"][0]
        self.assertEqual(extra["name"], "Extra")
        self.assertEqual(extra["artists"], ["Cora"])
        self.assertEqual(extra["image"], "https://i.scdn.co/image/extra")

    def test_spaced_artist_name_is_quoted_ahead_of_title_words(self):
        recent = {"items": [
            {"track": _catalog_track("1", "Fake Empire", "The National", "al1", "Boxer")},
            {"track": _catalog_track("2", "Bloodbuzz Ohio", "The National", "al2", "High Violet")},
            {"track": _catalog_track("3", "Hyperballad", "Bjork", "al3", "Post")},
        ]}
        api = FakeDiscoverAPI(recent=recent, search={"tracks": {"items": []}})

        response = self._fetch(api)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(api.calls), 2)
        self._assert_two_reads(api)
        query = api.calls[1][1]["q"]
        self.assertTrue(query.startswith('"The National"'))
        self.assertIn("fake", query)
        self.assertNotIn("Bjork", query)
        self.assertLessEqual(len(query), 100)
        self.assertEqual(api.calls[1][1]["limit"], 10)

    def test_title_words_are_used_when_plays_have_no_artist(self):
        recent = {"items": [
            {"track": _catalog_track("t1", "Lonely Road", "", "al1", "Album")},
            {"track": _catalog_track("t2", "Lonely Heart", "", "al1", "Album")},
        ]}
        api = FakeDiscoverAPI(
            recent=recent,
            search={"tracks": {"items": [
                _catalog_track("t9", "Found", "Cora", "al9", "Found Album"),
            ]}},
        )

        response = self._fetch(api)

        self.assertEqual(response.status_code, 200)
        self._assert_two_reads(api)
        self.assertEqual([call[0] for call in api.calls], ["me/player/recently-played", "search"])
        query = api.calls[1][1]["q"]
        self.assertTrue(query.startswith("lonely"))
        self.assertIn(" OR ", query)
        self.assertLessEqual(len(query), 100)
        body = response.json()
        self.assertEqual(body["playlists"], [])
        self.assertEqual(body["tracks"][0]["id"], "t9")
        self.assertEqual(body["albums"][0]["id"], "al9")

    def test_empty_recent_plays_read_saved_tracks_instead_of_search(self):
        saved = _catalog_track("s1", "Kept Song", "Ada", "al-kept", "Kept", duration_ms=90000)
        api = FakeDiscoverAPI(
            recent={"items": []},
            saved={"items": [
                {"added_at": "2026-01-01T00:00:00Z", "track": saved},
                {"track": None},
            ]},
        )

        response = self._fetch(api)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(api.urls), 2)
        self._assert_two_reads(api)
        self.assertEqual(api.calls[0], ("me/player/recently-played", {"limit": 10}))
        self.assertEqual(api.calls[1], ("me/tracks", {"limit": 20}))
        self.assertNotIn("search", " ".join(api.urls))
        body = response.json()
        self.assertEqual(set(body), {"playlists", "albums", "tracks"})
        self.assertEqual(body["playlists"], [])
        self.assertEqual(body["tracks"][0]["name"], "Kept Song")
        self.assertEqual(body["tracks"][0]["artists"], ["Ada"])
        self.assertEqual(body["tracks"][0]["album"], "Kept")
        self.assertEqual(body["tracks"][0]["duration_ms"], 90000)
        self.assertEqual(body["tracks"][0]["image"], "https://i.scdn.co/image/al-kept")
        self.assertEqual(body["albums"][0]["id"], "al-kept")
        self.assertEqual(body["albums"][0]["name"], "Kept")
        self.assertEqual(body["albums"][0]["artists"], ["Ada"])

    def test_null_recent_tracks_count_as_empty_history(self):
        api = FakeDiscoverAPI(
            recent={"items": [{"track": None}, {"played_at": "2026-01-01T00:00:00Z"}]},
            saved={"items": [{
                "track": _catalog_track("s2", "Shelf", "Bea", "al2", "Shelf Album"),
            }]},
        )

        response = self._fetch(api)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([call[0] for call in api.calls], ["me/player/recently-played", "me/tracks"])
        self.assertEqual(api.calls[1][1]["limit"], 20)
        self._assert_two_reads(api)
        self.assertEqual(response.json()["tracks"][0]["name"], "Shelf")
        self.assertEqual(response.json()["playlists"], [])

    def test_a_long_artist_name_stays_within_the_search_cap(self):
        artist = "A" * 180
        api = FakeDiscoverAPI(
            recent={"items": [{"track": _catalog_track("t1", "Song", artist, "al", "Album")}]},
            search={"tracks": {"items": []}},
        )

        response = self._fetch(api)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(api.calls), 2)
        query = api.calls[1][1]["q"]
        self.assertLessEqual(len(query), 100)
        self.assertTrue(query.startswith("A"))
        self._assert_two_reads(api)

    def test_each_refresh_stops_at_two_reads(self):
        api = FakeDiscoverAPI(
            recent={"items": [{"track": _catalog_track("t1", "Blue Moon", "Ada", "al", "Album")}]},
            search={"tracks": {"items": []}, "albums": {"items": []}, "playlists": {"items": []}},
        )

        first = self._fetch(api)
        second = self._fetch(api)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(api.urls), 4)
        for start in (0, 2):
            pair = api.urls[start:start + 2]
            self.assertEqual(len(pair), 2)
            blob = "\n".join(pair)
            for banned in FORBIDDEN_DISCOVER_URLS:
                self.assertNotIn(banned, blob)
        self.assertEqual(
            [call[0] for call in api.calls],
            ["me/player/recently-played", "search", "me/player/recently-played", "search"],
        )

    def test_search_can_fill_a_playlist_card(self):
        api = FakeDiscoverAPI(
            recent={"items": [{"track": _catalog_track("t1", "Blue Moon", "Ada", "al", "Album")}]},
            search={
                "tracks": {"items": []},
                "albums": {"items": []},
                "playlists": {"items": [{
                    "id": "pl1",
                    "name": "Night Bus",
                    "description": "late",
                    "images": [{"url": "https://i.scdn.co/image/pl1"}],
                    "tracks": {"total": 8},
                    "owner": {"display_name": "Ada", "id": "ada"},
                    "type": "playlist",
                }]},
            },
        )

        response = self._fetch(api)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(api.urls), 2)
        self._assert_two_reads(api)
        self.assertEqual(response.json()["playlists"], [{
            "id": "pl1",
            "name": "Night Bus",
            "description": "late",
            "image": "https://i.scdn.co/image/pl1",
            "tracks_count": 8,
            "owner": "Ada",
            "type": "playlist",
        }])

    def test_discover_requires_a_linked_account(self):
        response = self.client.get("/discover/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")

    def test_discover_template_still_reads_playlists_albums_and_tracks(self):
        template = (Path(__file__).resolve().parent / "templates" / "player" / "index.html").read_text()
        self.assertIn("function displayDiscover", template)
        self.assertIn("data.playlists", template)
        self.assertIn("data.albums", template)
        self.assertIn("data.tracks", template)
        self.assertIn("item.tracks_count", template)
        self.assertIn("track.artists.join", template)
        self.assertIn("item.artists.join", template)
        self.assertIn("track.duration_ms", template)
