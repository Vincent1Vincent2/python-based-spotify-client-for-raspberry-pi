import json
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
        self.assertEqual(feel_name(["hype", "calm"]), "Calm Hype")
        self.assertEqual(feel_name(["calm", "hype"]), feel_name(["hype", "calm"]))
        self.assertEqual(
            feel_name(["romantic", "hype", "focus", "calm"]),
            "Calm Focus Hype Romantic",
        )
        self.assertLessEqual(
            len(feel_name(["romantic", "hype", "focus", "calm", "mad", "happy", "sad"])),
            40,
        )

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
        both_new = {"uri": "spotify:track:c1", "name": "peaceful banger", "artists": [], "album": ""}
        only_new = {"uri": "spotify:track:c2", "name": "peaceful morning", "artists": [], "album": ""}
        self.assertGreater(
            score_track(both_new, ["hype", "calm"]),
            score_track(only_new, ["hype", "calm"]),
        )

    def test_mad_does_not_match_inside_another_word(self):
        track = {"uri": "spotify:track:3", "name": "made of gold", "artists": [], "album": ""}
        self.assertEqual(score_track(track, ["mad"]), 0)
        later = {"uri": "spotify:track:w", "name": "hyper focusing romanceable", "artists": [], "album": ""}
        self.assertEqual(score_track(later, ["hype"]), 0)
        self.assertEqual(score_track(later, ["focus"]), 0)
        self.assertEqual(score_track(later, ["romantic"]), 0)

    def test_query_leads_with_the_song_that_is_ending_and_stays_short(self):
        query = build_query(
            ["sad", "mad"],
            {"name": "Lonely Road", "artists": ["A" * 90], "uri": "spotify:track:9"},
        )
        self.assertTrue(query.startswith("lonely"))
        self.assertLessEqual(len(query), QUERY_CHAR_LIMIT)
        self.assertNotIn("A" * 90, query)
        self.assertIn("sad", query)

    def test_new_mood_query_leads_with_the_seed_title_and_stays_short(self):
        query = build_query(
            ["hype", "calm", "focus", "romantic"],
            {"name": "Paper Planes", "artists": ["A" * 90], "uri": "spotify:track:p"},
        )
        self.assertTrue(query.startswith("paper"))
        self.assertLessEqual(len(query), QUERY_CHAR_LIMIT)
        self.assertLessEqual(len(query), 100)
        self.assertNotIn("A" * 90, query)

    def test_same_artist_is_closer_than_an_unrelated_title(self):
        left = {"name": "blue", "artists": ["Ada"]}
        same = {"name": "other", "artists": ["Ada"]}
        other = {"name": "other", "artists": ["Bea"]}
        self.assertGreater(similarity(left, same), similarity(left, other))

    def test_generated_playlists_are_recognized(self):
        self.assertTrue(is_generated_playlist_name("Sad Mad Radio"))
        self.assertTrue(is_generated_playlist_name("Sad Mad 01"))
        self.assertTrue(is_generated_playlist_name("Calm Focus Radio"))
        self.assertTrue(is_generated_playlist_name("Calm Focus 01"))
        self.assertFalse(is_generated_playlist_name("Sad Songs"))
        self.assertFalse(is_generated_playlist_name("Calm Songs"))

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


class PlayerShellRenderTests(TestCase):
    def test_index_template_renders_controls_and_accent(self):
        from pathlib import Path

        from django.template.loader import render_to_string

        html = render_to_string(
            "player/index.html",
            {
                "client_id": "client-id",
                "access_token": "access-token",
                "use_web_player": True,
                "devices": [],
                "accounts": [],
                "active_account": None,
                "selected_device_id": None,
            },
        )
        self.assertIn("playBtn", html)
        self.assertIn("feelStart", html)
        self.assertIn('id="searchInput"', html)
        self.assertIn('id="progressTrack"', html)
        self.assertIn('id="deviceList"', html)
        self.assertIn('id="tab-feel"', html)
        css_path = Path(__file__).resolve().parent / "static" / "player" / "css" / "variables.css"
        stylesheet = css_path.read_text(encoding="utf-8")
        self.assertTrue("--color-accent" in html or "--color-accent" in stylesheet)


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
        self.assertIn('data-emotion="calm"', body)
        self.assertIn('data-emotion="focus"', body)
        self.assertIn('data-emotion="hype"', body)
        self.assertIn('data-emotion="romantic"', body)
        self.assertIn(">Calm</button>", body)
        self.assertIn(">Focus</button>", body)
        self.assertIn(">Hype</button>", body)
        self.assertIn(">Romantic</button>", body)
        self.assertIn("Keep going after the last song", body)

        status = client.get("/feel/status/")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["active"])


class AlbumCardTests(TestCase):
    def _albums_response(self, items):
        from unittest.mock import patch

        from django.test import RequestFactory

        from player.views import albums

        calls = []

        class Api:
            def get_user_saved_albums(self, limit=50, offset=0):
                calls.append(("GET /me/albums", limit, offset))
                return FakeResponse({
                    "items": items,
                    "next": None,
                    "total": len([item for item in items if item]),
                })

            def get_album(self, album_id):
                calls.append(("GET /albums", album_id))
                raise AssertionError("album cards must use the image on GET /me/albums")

        request = RequestFactory().get("/albums/?offset=0&limit=50")
        with patch("player.views.get_spotify_client", return_value=Api()):
            response = albums(request)
        return response, calls

    def test_album_json_includes_image_when_the_album_has_images(self):
        album = {
            "id": "al1",
            "name": "Night Drive",
            "artists": [{"name": "Ada"}, {"name": "Bea"}],
            "images": [
                {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640},
                {"url": "https://i.scdn.co/image/small", "width": 64, "height": 64},
            ],
            "release_date": "2020-05-01",
            "total_tracks": 9,
        }
        response, calls = self._albums_response([
            {"added_at": "2024-01-01T00:00:00Z", "album": album},
        ])

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(calls, [("GET /me/albums", 50, 0)])
        self.assertEqual(len(body["albums"]), 1)
        self.assertEqual(body["albums"][0]["image"], "https://i.scdn.co/image/large")
        self.assertEqual(body["albums"][0]["name"], "Night Drive")
        self.assertEqual(body["albums"][0]["artists"], ["Ada", "Bea"])

    def test_missing_images_list_yields_a_null_image(self):
        missing = {
            "id": "al2",
            "name": "No Cover",
            "artists": [{"name": "Ada"}],
            "release_date": "2019",
            "total_tracks": 1,
        }
        empty = {
            "id": "al3",
            "name": "Empty Cover",
            "artists": [{"name": "Bea"}],
            "images": [],
            "release_date": "2018",
            "total_tracks": 2,
        }
        response, calls = self._albums_response([
            {"added_at": "2024-01-01T00:00:00Z", "album": missing},
            {"added_at": "2024-01-02T00:00:00Z", "album": empty},
            None,
        ])

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(calls, [("GET /me/albums", 50, 0)])
        self.assertEqual(len(body["albums"]), 2)
        self.assertIsNone(body["albums"][0]["image"])
        self.assertEqual(body["albums"][0]["name"], "No Cover")
        self.assertIsNone(body["albums"][1]["image"])
        self.assertNotIn("error", body)

    def test_player_page_links_album_cards_once(self):
        import time
        from unittest.mock import patch

        account = SpotifyAccount.objects.create(
            spotify_user_id="album-card-user",
            display_name="Albums",
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
        self.assertEqual(body.count("player/css/album-cards.css"), 1)
        self.assertIn("album-card-cover", body)
        self.assertIn("album-card-artist", body)
        self.assertIn("function displayAlbums", body)
        self.assertIn('class="playlist-item"', body)
        self.assertNotIn("playlist-cards.css", body)

    def test_index_contains_states_js(self):
        import time
        from unittest.mock import patch

        account = SpotifyAccount.objects.create(
            spotify_user_id="states-user",
            display_name="States",
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
        self.assertEqual(body.count("player/js/states.js"), 1)
        self.assertEqual(body.count("player/css/states.css"), 1)
        self.assertIn("renderState(document.getElementById('playlistsGrid'), 'loading', 'Loading playlists...')", body)
        self.assertIn("renderState(document.getElementById('albumsGrid'), 'loading', 'Loading albums...')", body)
        self.assertIn("renderState(document.getElementById('songsList'), 'loading', 'Loading songs...')", body)
        self.assertIn("renderState(document.getElementById('discoverContent'), 'loading', 'Loading discoveries...')", body)
        self.assertIn("renderState(grid, 'empty', 'No playlists found')", body)
        self.assertIn("renderState(grid, 'empty', 'No albums found')", body)
        self.assertIn("renderState(list, 'empty', 'No saved songs found')", body)
        self.assertIn("renderState(contentDiv, 'empty', 'No discoveries found')", body)
        self.assertNotIn("playlistsGrid').innerHTML =", body)
        self.assertNotIn("albumsGrid').innerHTML =", body)
        self.assertNotIn("songsList').innerHTML =", body)

