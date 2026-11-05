import json
import time
from unittest.mock import patch

from django.test import Client, TestCase

from player.features.smart_mixes.filter import filter_saved_tracks
from player.features.smart_mixes.mix import build_smart_mix, session_counter_key
from player.models import SpotifyAccount


def saved(name, artist="Ada", release_date="2001-01-01", number=1, album=True):
    """One GET /me/tracks item. album.release_date is optional."""
    if isinstance(artist, str):
        artists = [{"name": artist}]
    else:
        artists = list(artist)
    track = {
        "id": f"id{number}",
        "uri": f"spotify:track:{number}",
        "name": name,
        "artists": artists,
    }
    if album:
        album_body = {"name": "Album"}
        if release_date is not None:
            album_body["release_date"] = release_date
        track["album"] = album_body
    return {"added_at": "2024-01-01T00:00:00Z", "track": track}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload


class FakeAPI:
    def __init__(self, items):
        self.items = items
        self.calls = []
        self.created = []
        self.added = []
        self._next_id = 1

    def get_user_saved_tracks(self, limit=50, offset=0):
        self.calls.append(("saved_tracks", limit, offset))
        return FakeResponse({"items": self.items})

    def get_recommendations(self, **kwargs):
        self.calls.append(("recommendations", kwargs))
        return FakeResponse({"tracks": []})

    def search(self, q, type="track", limit=10, offset=0):
        self.calls.append(("search", q, limit))
        return FakeResponse({"tracks": {"items": []}})

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
        self.calls.append(("play", device_id, context_uri))
        return FakeResponse({}, status=204)


class Session(dict):
    """Enough of a Django session for the counter."""

    modified = False

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.modified = True


class SmartMixFilterTests(TestCase):
    def test_year_filter(self):
        items = [
            saved("Early", release_date="1991-04-01", number=1),
            saved("Edge", release_date="2000", number=2),
            saved("Later", release_date="2004-11", number=3),
            saved("Undated", release_date=None, number=4),
            saved("No album", release_date=None, number=5, album=False),
        ]
        found = filter_saved_tracks(items, year_from=2000)
        self.assertEqual([track["name"] for track in found], ["Edge", "Later"])

        unfiltered = filter_saved_tracks(items, year_from=None)
        self.assertEqual(
            [track["name"] for track in unfiltered],
            ["Early", "Edge", "Later", "Undated", "No album"],
        )

    def test_artist_filter(self):
        items = [
            saved("A", artist="Radiohead", number=1),
            saved("B", artist="The Beatles", number=2),
            saved(
                "C",
                artist=[{"name": "Guest"}, {"name": "radiohead"}],
                number=3,
            ),
        ]
        found = filter_saved_tracks(items, artist="  RaDiO ")
        self.assertEqual([track["name"] for track in found], ["A", "C"])

    def test_title_filter(self):
        items = [
            saved("Paranoid Android", artist="Radiohead", number=1),
            saved("Creep", artist="Radiohead", number=2),
        ]
        found = filter_saved_tracks(items, title="creep")
        self.assertEqual([track["uri"] for track in found], ["spotify:track:2"])

    def test_filters_all_have_to_match(self):
        items = [
            saved("Creep", artist="Radiohead", release_date="1992", number=1),
            saved("Creep", artist="Radiohead", release_date="2010-01-01", number=2),
            saved("Creep", artist="Someone", release_date="2010", number=3),
            saved("Karma Police", artist="Radiohead", release_date="2010", number=4),
        ]
        found = filter_saved_tracks(items, artist="radio", title="creep", year_from=2000)
        self.assertEqual([track["uri"] for track in found], ["spotify:track:2"])

    def test_cap_30(self):
        items = [saved("Nope", artist="Other", number=0)]
        items += [
            saved(f"Yes {index}", artist="Radiohead", number=index)
            for index in range(1, 41)
        ]
        found = filter_saved_tracks(items, artist="radiohead")
        self.assertEqual(len(found), 30)
        self.assertEqual(found[0]["name"], "Yes 1")
        self.assertEqual(found[-1]["name"], "Yes 30")
        self.assertEqual(found[-1]["uri"], "spotify:track:30")


class SmartMixBuildTests(TestCase):
    def test_empty_result_does_not_call_create(self):
        api = FakeAPI([saved("Hello", artist="The Beatles", release_date="1968", number=1)])
        session = Session()
        result = build_smart_mix(
            api,
            session,
            "user-a",
            artist="radiohead",
            device_id="device-1",
        )
        self.assertFalse(result["created"])
        self.assertEqual(result["tracks"], [])
        self.assertEqual(result["reads"], ["GET /me/tracks?limit=50"])
        self.assertEqual(api.calls, [("saved_tracks", 50, 0)])
        self.assertEqual(api.created, [])
        self.assertEqual(api.added, [])
        self.assertNotIn(session_counter_key("user-a"), session)

    def test_saves_private_mix_and_plays_it(self):
        items = [
            saved(f"Song {index}", artist="Radiohead", release_date="1997-05-28", number=index)
            for index in range(1, 33)
        ]
        api = FakeAPI(items)
        session = Session()
        result = build_smart_mix(
            api,
            session,
            "user-a",
            artist="radio",
            title="",
            year_from=1990,
            device_id="device-1",
        )
        self.assertTrue(result["created"])
        self.assertEqual(result["name"], "Mix 01")
        self.assertEqual(result["count"], 30)
        self.assertEqual(result["reads"], ["GET /me/tracks?limit=50"])
        self.assertEqual(
            [call[0] for call in api.calls],
            ["saved_tracks", "create", "add", "play"],
        )
        self.assertEqual(api.calls[0], ("saved_tracks", 50, 0))
        self.assertEqual(api.calls[1], ("create", "Mix 01", False))
        self.assertFalse(api.created[0]["public"])
        self.assertEqual(len(api.added), 1)
        self.assertEqual(len(api.added[0]["uris"]), 30)
        self.assertEqual(api.added[0]["uris"][0], "spotify:track:1")
        self.assertEqual(api.added[0]["uris"][-1], "spotify:track:30")
        self.assertEqual(api.calls[3], ("play", "device-1", "spotify:playlist:pl1"))
        self.assertEqual(session[session_counter_key("user-a")], 1)
        self.assertNotIn("recommendations", [call[0] for call in api.calls])

        second = FakeAPI(items[:2])
        again = build_smart_mix(second, session, "user-a", artist="radio", device_id="device-1")
        self.assertEqual(again["name"], "Mix 02")
        self.assertEqual(session[session_counter_key("user-a")], 2)

        other = FakeAPI(items[:2])
        other_account = build_smart_mix(
            other, session, "user-b", artist="radio", device_id="device-1",
        )
        self.assertEqual(other_account["name"], "Mix 01")
        self.assertEqual(session[session_counter_key("user-b")], 1)
        self.assertEqual(session[session_counter_key("user-a")], 2)


class SmartMixPageTests(TestCase):
    def setUp(self):
        self.account = SpotifyAccount.objects.create(
            spotify_user_id="mix-user",
            display_name="Mix",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )
        self.client = Client()
        session = self.client.session
        session["active_account_id"] = self.account.id
        session["use_web_player"] = False
        session["selected_device_id"] = "device-1"
        session.save()

    def test_player_page_shows_the_mix_tab(self):
        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)):
            page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="tab-mix"', body)
        self.assertIn(">Mix<", body)
        self.assertIn('id="mixArtist"', body)
        self.assertIn('id="mixTitle"', body)
        self.assertIn('id="mixYear"', body)
        self.assertIn("Artist contains", body)
        self.assertIn("Title contains", body)
        self.assertIn("Year from", body)

    def test_endpoint_stores_the_counter_on_the_session(self):
        api = FakeAPI([
            saved("Creep", artist="Radiohead", release_date="1993", number=1),
        ])
        with patch("player.features.smart_mixes.views.get_spotify_api", return_value=api):
            response = self.client.post(
                "/mix/",
                data=json.dumps({"artist": "radio", "title": "creep", "year_from": 1990}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Mix 01")
        self.assertTrue(body["created"])
        self.assertEqual(body["reads"], ["GET /me/tracks?limit=50"])
        self.assertEqual(
            self.client.session[session_counter_key(self.account.spotify_user_id)],
            1,
        )
        self.assertEqual(api.calls[0], ("saved_tracks", 50, 0))
        self.assertEqual([call[0] for call in api.calls], ["saved_tracks", "create", "add", "play"])
        self.assertTrue(all(item["public"] is False for item in api.created))

    def test_endpoint_empty_result_does_not_call_create(self):
        api = FakeAPI([
            saved("Hello", artist="The Beatles", release_date="1968", number=1),
        ])
        with patch("player.features.smart_mixes.views.get_spotify_api", return_value=api):
            response = self.client.post(
                "/mix/",
                data=json.dumps({"artist": "radiohead"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["created"])
        self.assertEqual(api.created, [])
        self.assertEqual(api.added, [])
        self.assertNotIn("create", [call[0] for call in api.calls])
        self.assertNotIn(
            session_counter_key(self.account.spotify_user_id),
            self.client.session,
        )
