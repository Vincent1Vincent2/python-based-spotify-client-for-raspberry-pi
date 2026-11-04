import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.template.loader import render_to_string

from player.feel import build_query, order_for_radio
from player.features.song_radio.radio import (
    PLAYLIST_SIZE,
    READ_LIMIT,
    SongRadioError,
    normalize_seed,
    song_radio_title,
    start_song_radio,
)
from player.models import SpotifyAccount


def _track(number, name, artist="Ada"):
    return {
        "id": f"id{number}",
        "uri": f"spotify:track:{number}",
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": "Album"},
    }


def _album_track(number, name, artist="Zed"):
    return {
        "id": f"alb{number}",
        "uri": f"spotify:track:alb{number}",
        "name": name,
        "artists": [{"name": artist}],
        "is_local": False,
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
    """Records Spotify calls the way player.tests.FakeAPI does."""

    def __init__(self, album_tracks=None, saved_tracks=None, search_tracks=None):
        self.album_tracks = album_tracks or []
        self.saved_tracks = saved_tracks or []
        self.search_tracks = search_tracks or []
        self.calls = []
        self.created = []
        self.added = []
        self._next_id = 1

    def get_album_tracks(self, album_id, limit=50, offset=0):
        self.calls.append(("album_tracks", album_id, limit, offset))
        return FakeResponse({"items": self.album_tracks})

    def get_user_saved_tracks(self, limit=50, offset=0):
        self.calls.append(("saved_tracks", limit, offset))
        return FakeResponse({"items": [{"track": track} for track in self.saved_tracks]})

    def search(self, q, type="track", limit=10, offset=0):
        self.calls.append(("search", q, type, limit, offset))
        return FakeResponse({"tracks": {"items": self.search_tracks}})

    def create_playlist(self, name, description="", public=False):
        self.calls.append(("create", name, public))
        playlist_id = f"pl{self._next_id}"
        self._next_id += 1
        self.created.append({
            "id": playlist_id,
            "name": name,
            "description": description,
            "public": public,
        })
        return FakeResponse({"id": playlist_id}, status=201)

    def add_playlist_items(self, playlist_id, uris):
        self.calls.append(("add", playlist_id, list(uris)))
        self.added.append({"id": playlist_id, "uris": list(uris)})
        return FakeResponse({}, status=201)

    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        self.calls.append(("play", device_id, context_uri, uris, offset))
        return FakeResponse({}, status=204)

    def get_recommendations(self, *args, **kwargs):
        self.calls.append(("recommendations",))
        raise AssertionError("recommendations must not be called")

    def get(self, endpoint, **kwargs):
        self.calls.append(("get", endpoint, kwargs))
        raise AssertionError(f"unexpected GET {endpoint}")


def _kinds(calls):
    return [call[0] for call in calls]


def _reads_before_writes(calls):
    reads = []
    for call in calls:
        if call[0] in {"create", "add", "play"}:
            break
        reads.append(call)
    return reads


class SongRadioTests(SimpleTestCase):
    def _seed(self, album_id="alb9"):
        seed = {
            "name": "Blue Monday",
            "artists": ["Ada"],
            "uri": "spotify:track:seed",
        }
        if album_id:
            seed["album_id"] = album_id
        return seed

    def _album_page(self):
        tracks = [
            _album_track(index, f"parking lot {index}", "Zed")
            for index in range(40)
        ]
        tracks.append(_album_track("near", "Blue Monday Night", "Ada"))
        tracks.append({
            "id": "local",
            "uri": "spotify:local:file",
            "name": "desk recording",
            "artists": [{"name": "Ada"}],
            "is_local": True,
        })
        return tracks

    def _search_page(self):
        return [_track(f"s{index}", f"blue echo {index}", "Bea") for index in range(20)]

    def test_album_seed_uses_two_reads_and_one_private_playlist(self):
        api = FakeAPI(album_tracks=self._album_page(), search_tracks=self._search_page())
        seed = self._seed()
        with patch("player.features.song_radio.radio.order_for_radio", wraps=order_for_radio) as ordered, \
                patch("player.features.song_radio.radio.build_query", wraps=build_query) as built:
            result = start_song_radio(api, seed, "device-1")

        self.assertEqual(built.call_count, 1)
        self.assertEqual(built.call_args.args[1]["uri"], seed["uri"])
        self.assertEqual(ordered.call_count, 1)
        self.assertEqual(ordered.call_args.args[2]["uri"], seed["uri"])

        reads = _reads_before_writes(api.calls)
        self.assertLessEqual(len(reads), 2)
        self.assertEqual(len(reads), 2)
        self.assertEqual(reads[0][0], "album_tracks")
        self.assertEqual(reads[0][1], "alb9")
        self.assertEqual(reads[0][2], READ_LIMIT)
        self.assertEqual(reads[0][3], 0)
        self.assertEqual(reads[1][0], "search")
        self.assertEqual(reads[1][1], build_query([], normalize_seed(seed)[0]))
        self.assertEqual(reads[1][2], "track")
        self.assertEqual(reads[1][3], READ_LIMIT)
        self.assertNotIn("saved_tracks", _kinds(api.calls))
        self.assertNotIn("recommendations", _kinds(api.calls))
        self.assertNotIn("get", _kinds(api.calls))

        creates = [call for call in api.calls if call[0] == "create"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0][1], "Blue Monday Radio")
        self.assertIs(creates[0][2], False)
        self.assertEqual(len(api.created), 1)
        self.assertFalse(api.created[0]["public"])

        self.assertEqual(len(api.added), 1)
        uris = api.added[0]["uris"]
        self.assertEqual(len(uris), PLAYLIST_SIZE)
        self.assertEqual(len(uris), len(set(uris)))
        self.assertEqual(uris[0], "spotify:track:seed")
        self.assertNotIn("spotify:local:file", uris)
        self.assertLess(uris.index("spotify:track:albnear"), uris.index("spotify:track:alb0"))

        self.assertEqual(_kinds(api.calls), ["album_tracks", "search", "create", "add", "play"])
        self.assertEqual(api.calls[-1][1], "device-1")
        self.assertEqual(api.calls[-1][2], "spotify:playlist:pl1")
        self.assertIsNone(api.calls[-1][3])
        self.assertEqual(result["reads"], [
            "GET /albums/alb9/tracks?limit=50",
            "GET /search?limit=50",
        ])
        self.assertEqual(result["count"], 30)
        self.assertEqual(result["tracks"][0]["uri"], "spotify:track:seed")
        self.assertEqual(result["name"], "Blue Monday Radio")

    def test_saved_songs_when_the_seed_has_no_album(self):
        saved = [_track(index, f"blue saved {index}") for index in range(35)]
        api = FakeAPI(saved_tracks=saved, search_tracks=self._search_page())
        result = start_song_radio(api, self._seed(album_id=None), "device-1")
        reads = _reads_before_writes(api.calls)
        self.assertEqual(len(reads), 2)
        self.assertEqual(reads[0][0], "saved_tracks")
        self.assertEqual(reads[0][1], READ_LIMIT)
        self.assertNotIn("album_tracks", _kinds(api.calls))
        self.assertEqual(_kinds(api.calls).count("create"), 1)
        self.assertEqual(len(api.added[0]["uris"]), 30)
        self.assertEqual(result["reads"][0], "GET /me/tracks?limit=50")

    def test_album_uri_is_accepted_as_the_album_id(self):
        api = FakeAPI(album_tracks=self._album_page(), search_tracks=self._search_page())
        seed = self._seed(album_id=None)
        seed["album"] = {"uri": "spotify:album:fromuri", "name": "Days"}
        start_song_radio(api, seed, "device-1")
        self.assertEqual(api.calls[0][0], "album_tracks")
        self.assertEqual(api.calls[0][1], "fromuri")

    def test_empty_query_skips_the_search(self):
        api = FakeAPI(saved_tracks=[_track(1, "anything")])
        seed = {"name": "It", "artists": [], "uri": "spotify:track:it"}
        result = start_song_radio(api, seed, "device-1")
        self.assertEqual(_kinds(api.calls), ["saved_tracks", "create", "add", "play"])
        self.assertLessEqual(len(_reads_before_writes(api.calls)), 2)
        self.assertEqual(result["query"], "")
        self.assertEqual(result["name"], "It Radio")
        self.assertEqual(api.added[0]["uris"][0], "spotify:track:it")

    def test_a_short_pile_still_creates_once(self):
        api = FakeAPI(
            album_tracks=[_album_track(1, "blue room", "Ada")],
            search_tracks=[_track(2, "blue light", "Ada")],
        )
        result = start_song_radio(api, self._seed(), "device-1")
        self.assertEqual(_kinds(api.calls).count("create"), 1)
        self.assertEqual(_kinds(api.calls).count("search"), 1)
        self.assertEqual(len(api.added), 1)
        self.assertLess(result["count"], PLAYLIST_SIZE)
        self.assertGreaterEqual(result["count"], 1)
        self.assertLessEqual(len(result["reads"]), 2)

    def test_long_track_name_is_truncated_to_80_and_keeps_radio(self):
        title = song_radio_title("A" * 90)
        self.assertEqual(len(title), 80)
        self.assertTrue(title.endswith(" Radio"))
        self.assertTrue(title.startswith("A"))
        api = FakeAPI(album_tracks=self._album_page(), search_tracks=[])
        seed = self._seed()
        seed["name"] = "A" * 90
        start_song_radio(api, seed, "device-1")
        self.assertEqual(api.created[0]["name"], title)
        self.assertLessEqual(len(api.created[0]["name"]), 80)

    def test_missing_uri_does_not_call_spotify(self):
        api = FakeAPI()
        with self.assertRaises(SongRadioError):
            start_song_radio(api, {"name": "Blue", "artists": ["Ada"]}, "device-1")
        self.assertEqual(api.calls, [])

    def test_forbidden_playlist_create_does_not_add_or_play(self):
        api = FakeAPI(album_tracks=self._album_page(), search_tracks=self._search_page())

        def forbidden(name, description="", public=False):
            api.calls.append(("create", name, public))
            return FakeResponse({"error": {"message": "Insufficient client scope"}}, status=403)

        api.create_playlist = forbidden
        with self.assertRaises(SongRadioError):
            start_song_radio(api, self._seed(), "device-1")
        self.assertEqual(_kinds(api.calls), ["album_tracks", "search", "create"])
        self.assertEqual(api.added, [])

    def test_feature_source_does_not_call_recommendations_or_audio_features(self):
        root = Path(settings.BASE_DIR) / "player" / "features" / "song_radio"
        source = "\n".join(
            path.read_text()
            for path in root.rglob("*.py")
            if path.name != "tests.py"
        )
        self.assertNotIn("get_recommendations", source)
        self.assertNotIn("audio-features", source)
        self.assertNotIn("audio_features", source)
        self.assertNotIn("recommendations", source)


class SongRadioPageTests(SimpleTestCase):
    def test_index_includes_the_button_once(self):
        index_path = Path(settings.BASE_DIR) / "player" / "templates" / "player" / "index.html"
        source = index_path.read_text()
        include = '{% include "song_radio/button.html" %}'
        self.assertEqual(source.count(include), 1)

        html = render_to_string("player/index.html", {
            "client_id": "client",
            "access_token": "token",
            "devices": [],
            "use_web_player": True,
            "selected_device_id": None,
        })
        self.assertEqual(html.count('id="songRadioButton"'), 1)
        self.assertIn("Song radio", html)
        self.assertIn("/song-radio/", html)
        self.assertIn("JSON.stringify", html)
        self.assertIn("album_id", html)
        self.assertIn('"POST"', html)


class SongRadioEndpointTests(TestCase):
    def setUp(self):
        self.account = SpotifyAccount.objects.create(
            spotify_user_id="song-radio-user",
            display_name="Song",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=0,
        )
        self.client = Client()
        session = self.client.session
        session["active_account_id"] = self.account.id
        session["selected_device_id"] = "device-9"
        session["use_web_player"] = False
        session.save()

    def _post(self, payload, api=None):
        with patch("player.features.song_radio.views.get_spotify_api", return_value=api):
            return self.client.post(
                "/song-radio/",
                data=json.dumps(payload),
                content_type="application/json",
            )

    def test_posted_seed_stays_inside_two_reads_and_one_create(self):
        album = [_album_track(index, f"blue page {index}", "Ada") for index in range(36)]
        api = FakeAPI(album_tracks=album, search_tracks=[_track(index, f"blue hit {index}") for index in range(12)])
        response = self._post({
            "name": "Blue Monday",
            "artists": ["Ada"],
            "uri": "spotify:track:seed",
            "album_id": "alb9",
            "device_id": "device-9",
        }, api)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Blue Monday Radio")
        self.assertEqual(body["count"], 30)
        self.assertLessEqual(len(body["reads"]), 2)
        self.assertEqual(_kinds(api.calls), ["album_tracks", "search", "create", "add", "play"])
        self.assertEqual(_kinds(api.calls).count("create"), 1)
        self.assertIs(api.calls[2][2], False)
        self.assertEqual(len(api.added[0]["uris"]), 30)
        self.assertEqual(api.calls[-1][2], f"spotify:playlist:{body['playlist_id']}")

    def test_missing_device_does_not_read_spotify(self):
        session = self.client.session
        session["selected_device_id"] = None
        session["use_web_player"] = False
        session.save()
        api = FakeAPI()
        response = self._post({
            "name": "Blue Monday",
            "artists": ["Ada"],
            "uri": "spotify:track:seed",
        }, api)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "no_device")
        self.assertEqual(api.calls, [])

    def test_missing_session_is_unauthorized(self):
        client = Client()
        response = client.post(
            "/song-radio/",
            data=json.dumps({"name": "Blue", "artists": ["Ada"], "uri": "spotify:track:1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
