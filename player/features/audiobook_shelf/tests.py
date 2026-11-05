"""Fakes for the Books shelf: list parse, chapter parse, and no batch read."""
import time
from pathlib import Path
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase

from player.features.audiobook_shelf import views as audiobook_views
from player.features.audiobook_shelf.views import (
    AudiobookError,
    AudiobookScopeError,
    load_audiobook,
    load_saved_audiobooks,
    parse_chapters,
    parse_saved_audiobooks,
    play_chapter,
    remove_audiobook,
    save_audiobook,
)
from player.models import SpotifyAccount
from player.views import SPOTIFY_SCOPE


EXISTING_SCOPES = (
    "user-modify-playback-state",
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-read-playback-position",
    "streaming",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "user-library-read",
)


def _book(**overrides):
    payload = {
        "id": "book1",
        "name": "A Psalm for the Wild-Built",
        "uri": "spotify:audiobook:book1",
        "authors": [{"name": "Becky Chambers"}],
        "narrators": [{"name": "Em Grosland"}],
        "publisher": "Macmillan",
        "description": "A monk and a robot.",
        "edition": "Unabridged",
        "explicit": False,
        "languages": ["en"],
        "images": [{"url": "https://i.example/cover.jpg", "height": 300, "width": 300}],
        "total_chapters": 6,
        "type": "audiobook",
    }
    payload.update(overrides)
    return payload


def _chapter(**overrides):
    payload = {
        "id": "ch1",
        "name": "The City",
        "uri": "spotify:episode:ep1",
        "chapter_number": 1,
        "duration_ms": 120000,
        "description": "Opening",
        "explicit": False,
        "type": "episode",
        "is_playable": True,
        "images": [{"url": "https://i.example/ch.jpg"}],
    }
    payload.update(overrides)
    return payload


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class FakeAPI:
    def __init__(self, gets=None, put_status=200, delete_status=200, play_status=204, play_body=None):
        self._gets = list(gets or [])
        self.put_status = put_status
        self.delete_status = delete_status
        self.play_status = play_status
        self.play_body = {} if play_body is None else play_body
        self.calls = []

    def get(self, endpoint, **kwargs):
        self.calls.append(("GET", endpoint, kwargs.get("params")))
        if not self._gets:
            return FakeResponse({})
        return self._gets.pop(0)

    def put(self, endpoint, **kwargs):
        self.calls.append(("PUT", endpoint, kwargs.get("params")))
        return FakeResponse({}, self.put_status)

    def delete(self, endpoint, **kwargs):
        self.calls.append(("DELETE", endpoint, kwargs.get("params")))
        return FakeResponse({}, self.delete_status)

    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        self.calls.append(("PLAY", list(uris or []), device_id, context_uri))
        return FakeResponse(self.play_body, self.play_status)


class ListParseTests(SimpleTestCase):
    def test_list_parse_keeps_authors_image_and_skips_nulls(self):
        payload = {
            "href": "https://api.spotify.com/v1/me/audiobooks?offset=0&limit=50",
            "limit": 50,
            "next": "https://api.spotify.com/v1/me/audiobooks?offset=50&limit=50",
            "total": 3,
            "items": [
                _book(),
                None,
                {"id": "", "name": "Missing id"},
                {"audiobook": _book(id="book2", name="Wrapped", authors=["Ada"])},
            ],
        }
        parsed = parse_saved_audiobooks(payload)
        self.assertEqual([book["id"] for book in parsed["audiobooks"]], ["book1", "book2"])
        first = parsed["audiobooks"][0]
        self.assertEqual(first["name"], "A Psalm for the Wild-Built")
        self.assertEqual(first["authors"], ["Becky Chambers"])
        self.assertEqual(first["narrators"], ["Em Grosland"])
        self.assertEqual(first["image"], "https://i.example/cover.jpg")
        self.assertEqual(first["publisher"], "Macmillan")
        self.assertEqual(first["total_chapters"], 6)
        self.assertEqual(first["uri"], "spotify:audiobook:book1")
        self.assertEqual(first["languages"], ["en"])
        self.assertEqual(parsed["audiobooks"][1]["authors"], ["Ada"])
        self.assertEqual(parsed["total"], 3)
        self.assertEqual(parsed["limit"], 50)
        self.assertNotIn("next", parsed)
        self.assertNotIn("items", parsed)

    def test_list_is_one_saved_audiobooks_read(self):
        api = FakeAPI(gets=[FakeResponse({
            "items": [_book()],
            "total": 1,
            "limit": 50,
            "next": "https://api.spotify.com/v1/me/audiobooks?offset=50&limit=50",
        })])
        result = load_saved_audiobooks(api)
        self.assertEqual(api.calls, [("GET", "me/audiobooks", {"limit": 50})])
        self.assertEqual(result["audiobooks"][0]["name"], "A Psalm for the Wild-Built")
        self.assertNotIn("chapters", result["audiobooks"][0])

    def test_list_forbidden_is_needs_scope_and_does_not_retry(self):
        api = FakeAPI(gets=[FakeResponse(
            {"error": {"status": 403, "message": "Insufficient client scope"}},
            status=403,
        )])
        with self.assertRaises(AudiobookScopeError) as caught:
            load_saved_audiobooks(api)
        self.assertEqual(caught.exception.code, "needs_scope")
        self.assertEqual(str(caught.exception), "Insufficient client scope")
        self.assertEqual(len(api.calls), 1)


class ChapterParseTests(SimpleTestCase):
    def test_chapter_parse_keeps_episode_track_and_chapter_uris(self):
        parsed = parse_chapters({
            "limit": 50,
            "total": 4,
            "items": [
                _chapter(),
                _chapter(
                    id="ch2",
                    name="The Road",
                    uri="spotify:track:tr1",
                    chapter_number=2,
                    duration_ms=90000,
                    type="track",
                ),
                _chapter(
                    id="ch3",
                    name="The Forest",
                    uri="spotify:chapter:ch3",
                    chapter_number=3,
                    duration_ms=1500000,
                    type="chapter",
                    is_playable=False,
                ),
                None,
                {"name": "No link"},
            ],
        })
        self.assertEqual(
            [chapter["uri"] for chapter in parsed["chapters"]],
            ["spotify:episode:ep1", "spotify:track:tr1", "spotify:chapter:ch3"],
        )
        self.assertEqual(parsed["chapters"][0]["name"], "The City")
        self.assertEqual(parsed["chapters"][0]["chapter_number"], 1)
        self.assertEqual(parsed["chapters"][0]["duration_ms"], 120000)
        self.assertEqual(parsed["chapters"][0]["image"], "https://i.example/ch.jpg")
        self.assertTrue(parsed["chapters"][0]["is_playable"])
        self.assertEqual(parsed["chapters"][2]["type"], "chapter")
        self.assertFalse(parsed["chapters"][2]["is_playable"])
        self.assertEqual(parsed["total"], 4)
        self.assertEqual(parsed["limit"], 50)

    def test_detail_reads_the_book_then_its_chapters(self):
        api = FakeAPI(gets=[
            FakeResponse(_book(
                chapters={
                    "items": [_chapter(id="embedded", name="Do not use", uri="spotify:episode:nope")],
                },
            )),
            FakeResponse({
                "items": [
                    _chapter(),
                    _chapter(id="ch3", name="The Forest", uri="spotify:chapter:ch3", chapter_number=3, duration_ms=5000, type="chapter"),
                ],
                "total": 2,
                "limit": 50,
            }),
        ])
        detail = load_audiobook(api, "book1")
        self.assertEqual(api.calls, [
            ("GET", "audiobooks/book1", None),
            ("GET", "audiobooks/book1/chapters", {"limit": 50}),
        ])
        self.assertEqual(detail["authors"], ["Becky Chambers"])
        self.assertEqual([chapter["id"] for chapter in detail["chapters"]], ["ch1", "ch3"])
        self.assertEqual(detail["chapters"][1]["uri"], "spotify:chapter:ch3")
        self.assertEqual(detail["chapters"][1]["duration_ms"], 5000)
        self.assertEqual(detail["chapters_total"], 2)
        self.assertNotIn("items", detail)


class PlaybackAndLibraryTests(SimpleTestCase):
    def test_episode_and_track_uris_start_playback(self):
        api = FakeAPI(play_status=204)
        episode = play_chapter(api, "spotify:episode:ep1", device_id="dev")
        track = play_chapter(api, "spotify:track:tr1", device_id="dev")
        self.assertEqual(episode, {"status": "playing", "uri": "spotify:episode:ep1"})
        self.assertEqual(track["uri"], "spotify:track:tr1")
        self.assertEqual(api.calls, [
            ("PLAY", ["spotify:episode:ep1"], "dev", None),
            ("PLAY", ["spotify:track:tr1"], "dev", None),
        ])

    def test_chapter_uri_is_still_sent_and_spotify_error_is_kept(self):
        message = "Player command failed: Restriction violated"
        api = FakeAPI(
            play_status=403,
            play_body={"error": {"status": 403, "message": message}},
        )
        with self.assertRaises(AudiobookScopeError) as caught:
            play_chapter(api, "spotify:chapter:ch3", device_id="device-1")
        self.assertEqual(caught.exception.code, "needs_scope")
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(api.calls, [("PLAY", ["spotify:chapter:ch3"], "device-1", None)])

    def test_playback_rejection_that_is_not_forbidden_stays_a_playback_error(self):
        api = FakeAPI(
            play_status=400,
            play_body={"error": {"status": 400, "message": "Invalid uri"}},
        )
        with self.assertRaises(AudiobookError) as caught:
            play_chapter(api, "spotify:chapter:ch3")
        self.assertEqual(caught.exception.code, "playback_error")
        self.assertEqual(str(caught.exception), "Invalid uri")
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(api.calls[0][1], ["spotify:chapter:ch3"])

    def test_other_uri_kinds_are_not_sent(self):
        api = FakeAPI()
        with self.assertRaises(AudiobookError) as caught:
            play_chapter(api, "spotify:show:show1")
        self.assertEqual(caught.exception.code, "bad_uri")
        self.assertEqual(api.calls, [])

    def test_save_and_remove_use_library_uris(self):
        api = FakeAPI()
        saved = save_audiobook(api, "book1")
        removed = remove_audiobook(api, "book1")
        self.assertEqual(saved, {
            "status": "saved",
            "id": "book1",
            "uri": "spotify:audiobook:book1",
        })
        self.assertEqual(removed["status"], "removed")
        self.assertEqual(api.calls, [
            ("PUT", "me/library", {"uris": "spotify:audiobook:book1"}),
            ("DELETE", "me/library", {"uris": "spotify:audiobook:book1"}),
        ])

    def test_library_forbidden_is_needs_scope(self):
        api = FakeAPI(put_status=403)
        api.put = lambda endpoint, **kwargs: _forbidden_put(api, endpoint, kwargs)
        with self.assertRaises(AudiobookScopeError) as caught:
            save_audiobook(api, "book1")
        self.assertEqual(caught.exception.code, "needs_scope")
        self.assertEqual(api.calls, [("PUT", "me/library", {"uris": "spotify:audiobook:book1"})])


def _forbidden_put(api, endpoint, kwargs):
    api.calls.append(("PUT", endpoint, kwargs.get("params")))
    return FakeResponse(
        {"error": {"status": 403, "message": "Insufficient client scope"}},
        status=403,
    )


class FeatureSourceTests(SimpleTestCase):
    def test_batch_endpoint_is_not_in_the_feature_views_source(self):
        source = Path(audiobook_views.__file__).read_text(encoding="utf-8")
        self.assertNotIn("audiobooks?ids", source)
        self.assertIn('api.get("me/audiobooks", params={"limit": LIST_LIMIT})', source)
        self.assertIn('f"audiobooks/{audiobook_id}/chapters"', source)
        self.assertIn('api.put("me/library", params={"uris": uri})', source)
        self.assertIn('api.delete("me/library", params={"uris": uri})', source)
        self.assertIn("api.start_playback(device_id=device_id, uris=[playable])", source)
        root = Path(audiobook_views.__file__).resolve().parent
        for path in root.rglob("*.py"):
            if path.name == "tests.py":
                continue
            self.assertNotIn("audiobooks?ids", path.read_text(encoding="utf-8"), path.name)


class ScopeTests(SimpleTestCase):
    def test_scope_adds_library_modify_and_keeps_the_rest(self):
        scopes = SPOTIFY_SCOPE.split()
        self.assertEqual(set(scopes), set(EXISTING_SCOPES) | {"user-library-modify"})
        self.assertEqual(len(scopes), len(set(scopes)))
        self.assertEqual(scopes[-1], "user-library-modify")


def _account(spotify_user_id):
    return SpotifyAccount.objects.create(
        spotify_user_id=spotify_user_id,
        display_name="Reader",
        access_token="access",
        refresh_token="refresh",
        token_expires_at=time.time() + 3600,
    )


def _client_for(account):
    client = Client()
    session = client.session
    session["active_account_id"] = account.id
    session["use_web_player"] = True
    session.save()
    return client


class AudiobookViewTests(TestCase):
    def test_missing_session_is_unauthorized(self):
        response = Client().get("/books/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")

    def test_list_view_returns_the_parsed_shelf(self):
        api = FakeAPI(gets=[FakeResponse({"items": [_book()], "total": 1, "limit": 50})])
        with patch("player.features.audiobook_shelf.views.get_spotify_api", return_value=api):
            response = Client().get("/books/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["audiobooks"][0]["authors"], ["Becky Chambers"])
        self.assertEqual(api.calls, [("GET", "me/audiobooks", {"limit": 50})])

    def test_list_view_forbidden_returns_needs_scope(self):
        api = FakeAPI(gets=[FakeResponse(
            {"error": {"status": 403, "message": "Insufficient client scope"}},
            status=403,
        )])
        with patch("player.features.audiobook_shelf.views.get_spotify_api", return_value=api):
            response = Client().get("/books/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "needs_scope")
        self.assertEqual(response.json()["error"], "Insufficient client scope")

    def test_play_view_surfaces_a_rejected_chapter_uri(self):
        message = "Player command failed: Restriction violated"
        api = FakeAPI(play_status=403, play_body={"error": {"status": 403, "message": message}})
        with patch("player.features.audiobook_shelf.views.get_spotify_api", return_value=api):
            response = Client().post("/books/play-chapter/?uri=spotify:chapter:ch3&device_id=dev")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "needs_scope")
        self.assertEqual(response.json()["error"], message)
        self.assertEqual(api.calls, [("PLAY", ["spotify:chapter:ch3"], "dev", None)])

    def test_save_and_remove_views_call_the_library(self):
        api = FakeAPI()
        with patch("player.features.audiobook_shelf.views.get_spotify_api", return_value=api):
            saved = Client().post("/books/save/?id=book1")
            removed = Client().post("/books/remove/?id=book1")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["uri"], "spotify:audiobook:book1")
        self.assertEqual(removed.json()["status"], "removed")
        self.assertEqual(api.calls, [
            ("PUT", "me/library", {"uris": "spotify:audiobook:book1"}),
            ("DELETE", "me/library", {"uris": "spotify:audiobook:book1"}),
        ])

    def test_player_page_has_the_books_tab(self):
        client = _client_for(_account("books-page"))
        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="tab-books"', body)
        self.assertIn(">Books</button>", body)
        self.assertIn('id="content-books"', body)
        self.assertIn('id="booksGrid"', body)
        self.assertIn('id="bookDetailError"', body)
        self.assertIn("/books/", body)
        self.assertIn("/books/detail/", body)
        self.assertIn("/books/play-chapter/", body)
        self.assertIn("/books/save/", body)
        self.assertIn("/books/remove/", body)
        self.assertIn("needs_scope", body)
        self.assertIn("/login/?auth=1", body)
        self.assertNotIn("audiobooks?ids", body)
        self.assertIn("Feel radio", body)

    def test_reconnect_asks_for_library_modify_and_keeps_existing_scopes(self):
        client = _client_for(_account("books-reauth"))
        home = client.get("/login/")
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], "/")
        reconnect = client.get("/login/?auth=1")
        self.assertEqual(reconnect.status_code, 302)
        location = reconnect["Location"]
        self.assertIn("https://accounts.spotify.com/authorize?", location)
        self.assertIn("user-library-modify", location)
        for scope in EXISTING_SCOPES:
            self.assertIn(scope, location)
