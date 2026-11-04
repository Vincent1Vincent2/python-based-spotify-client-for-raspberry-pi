import json
from unittest.mock import patch

from django.test import Client, TestCase

from player.features.playlist_editor.service import (
    PAGE_SIZE,
    PlaylistEditorError,
    add_track,
    create_private_playlist,
    insert_before_index,
    list_playlists,
    move_track,
    normalize_track_uri,
    playlist_detail,
    remove_from_library,
    remove_track,
    reorder_move,
    update_playlist,
)
from player.spotify_api import SpotifyAPI


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.text = ""

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class EmptyResponse:
    status_code = 200
    text = ""

    def json(self):
        raise ValueError("empty body")


class FakeAPI:
    def __init__(self, public=False, total=4, uris=None, snapshot="snap"):
        self.public = public
        self.total = total
        self.uris = list(uris or [
            "spotify:track:aaa",
            "spotify:track:bbb",
            "spotify:track:ccc",
            "spotify:track:ddd",
        ])
        self.snapshot = snapshot
        self.calls = []

    def get_user_playlists(self, limit=50, offset=0):
        self.calls.append(("playlists", limit, offset))
        return FakeResponse({
            "total": 1,
            "next": None,
            "items": [{
                "id": "pl1",
                "name": "Night",
                "description": "Quiet",
                "public": False,
                "snapshot_id": self.snapshot,
                "owner": {"display_name": "Ada"},
                "images": [],
                "items": {"total": self.total},
            }],
        })

    def get_playlist(self, playlist_id):
        self.calls.append(("playlist", playlist_id))
        return FakeResponse({
            "id": playlist_id,
            "name": "Night",
            "description": "Quiet",
            "public": self.public,
            "snapshot_id": self.snapshot,
            "owner": {"id": "me", "display_name": "Ada"},
            "images": [{"url": "https://example.test/cover.jpg"}],
            "items": {"total": self.total},
        })

    def get_playlist_items(self, playlist_id, limit=50, offset=0):
        self.calls.append(("items", playlist_id, limit, offset))
        rows = []
        for uri in self.uris:
            rows.append({
                "item": {
                    "uri": uri,
                    "id": uri.split(":")[-1],
                    "name": uri.split(":")[-1],
                    "artists": [{"name": "Ada"}],
                    "album": {"name": "Album", "images": [{"url": "https://example.test/t.jpg"}]},
                    "duration_ms": 1000,
                }
            })
        page = rows[offset:offset + limit]
        return FakeResponse({
            "items": page,
            "total": len(self.uris),
            "limit": limit,
            "offset": offset,
            "next": "next" if offset + limit < len(self.uris) else None,
        })

    def create_playlist(self, name, description="", public=False):
        self.calls.append(("create", name, description, public))
        return FakeResponse({
            "id": "new1",
            "name": name,
            "description": description,
            "snapshot_id": "created",
        }, status=201)

    def update_playlist_details(self, playlist_id, name=None, description=None):
        body = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        self.calls.append(("update", playlist_id, body))
        return EmptyResponse()

    def remove_playlist_from_library(self, playlist_id):
        self.calls.append(("unfollow", playlist_id))
        return EmptyResponse()

    def add_playlist_items(self, playlist_id, uris):
        self.calls.append(("add", playlist_id, list(uris)))
        return FakeResponse({"snapshot_id": "added"}, status=201)

    def remove_playlist_items(self, playlist_id, uris, snapshot_id=None, positions=None):
        self.calls.append(("remove", playlist_id, list(uris), snapshot_id, positions))
        return FakeResponse({"snapshot_id": "removed"})

    def reorder_playlist_items(self, playlist_id, range_start, insert_before, range_length=1, snapshot_id=None):
        self.calls.append((
            "reorder",
            playlist_id,
            range_start,
            insert_before,
            range_length,
            snapshot_id,
        ))
        return FakeResponse({"snapshot_id": "moved"})


class ReorderRuleTests(TestCase):
    def test_documented_examples_and_one_slot_moves(self):
        self.assertEqual(insert_before_index(0, 9), 10)
        self.assertEqual(insert_before_index(9, 0), 0)
        self.assertEqual(reorder_move(3, "down", 10), (3, 5, 1))
        self.assertEqual(reorder_move(3, "up", 10), (3, 2, 1))
        self.assertEqual(reorder_move(8, "down", 10), (8, 10, 1))

    def test_edges_do_not_move(self):
        with self.assertRaises(PlaylistEditorError):
            reorder_move(0, "up", 4)
        with self.assertRaises(PlaylistEditorError):
            reorder_move(3, "down", 4)


class PlaylistEditorServiceTests(TestCase):
    def test_page_size_is_50(self):
        self.assertEqual(PAGE_SIZE, 50)

    def test_create_is_private_and_named(self):
        api = FakeAPI()
        created = create_private_playlist(api, "  Night   Drive ", "  late ")
        self.assertEqual(created["id"], "new1")
        self.assertEqual(created["public"], False)
        self.assertEqual(api.calls, [("create", "Night Drive", "late", False)])

    def test_blank_name_is_rejected_before_spotify(self):
        api = FakeAPI()
        with self.assertRaises(PlaylistEditorError):
            create_private_playlist(api, "   ")
        self.assertEqual(api.calls, [])

    def test_rename_and_description_send_only_those_fields(self):
        api = FakeAPI()
        updated = update_playlist(
            api, "pl1", name="Dawn", description="", fields=("name", "description"),
        )
        self.assertEqual(updated["name"], "Dawn")
        self.assertEqual(updated["description"], "")
        self.assertEqual(api.calls, [("update", "pl1", {"name": "Dawn", "description": ""})])
        self.assertNotIn("public", api.calls[0][2])

    def test_private_playlist_is_removed_with_followers(self):
        api = FakeAPI(public=False)
        result = remove_from_library(api, "pl1")
        self.assertTrue(result["removed"])
        self.assertEqual(api.calls[0][0], "playlist")
        self.assertEqual(api.calls[1], ("unfollow", "pl1"))

    def test_public_playlist_is_not_removed(self):
        api = FakeAPI(public=True)
        with self.assertRaises(PlaylistEditorError) as caught:
            remove_from_library(api, "pl1")
        self.assertEqual(caught.exception.code, "not_private")
        self.assertEqual([call[0] for call in api.calls], ["playlist"])

    def test_add_normalizes_a_track_url(self):
        api = FakeAPI()
        result = add_track(api, "pl1", "https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl?si=abc")
        self.assertEqual(result["uri"], "spotify:track:11dFghVXANMlKmJXsNCbNl")
        self.assertEqual(api.calls, [("add", "pl1", ["spotify:track:11dFghVXANMlKmJXsNCbNl"])])

    def test_episode_uri_is_rejected(self):
        with self.assertRaises(PlaylistEditorError):
            normalize_track_uri("spotify:episode:512ojhOuo1ktJprKbVcKyQ")

    def test_detail_reads_items_not_tracks_and_uses_the_item_field(self):
        api = FakeAPI()
        detail = playlist_detail(api, "pl1", 0)
        self.assertEqual(detail["tracks"][0]["name"], "aaa")
        self.assertEqual(detail["tracks"][0]["artists"], ["Ada"])
        self.assertEqual(detail["tracks"][0]["position"], 0)
        self.assertEqual(api.calls[1], ("items", "pl1", 50, 0))
        self.assertNotIn("playlist_tracks", [call[0] for call in api.calls])

    def test_legacy_track_wrapper_still_reads(self):
        api = FakeAPI()

        def legacy_items(playlist_id, limit=50, offset=0):
            api.calls.append(("items", playlist_id, limit, offset))
            return FakeResponse({
                "items": [{
                    "track": {
                        "uri": "spotify:track:legacy",
                        "id": "legacy",
                        "name": "Legacy",
                        "artists": [{"name": "Bea"}],
                        "album": {"name": "Old"},
                        "duration_ms": 5,
                    }
                }],
                "total": 1,
                "next": None,
            })

        api.get_playlist_items = legacy_items
        detail = playlist_detail(api, "pl1", 0)
        self.assertEqual(detail["tracks"][0]["uri"], "spotify:track:legacy")
        self.assertTrue(detail["tracks"][0]["available"])

    def test_list_uses_items_total_and_page_size_50(self):
        api = FakeAPI()
        page = list_playlists(api, 0)
        self.assertEqual(page["limit"], 50)
        self.assertEqual(page["playlists"][0]["tracks_count"], 4)
        self.assertTrue(page["playlists"][0]["private"])
        self.assertEqual(api.calls, [("playlists", 50, 0)])

    def test_remove_sends_the_position_and_checks_the_uri(self):
        api = FakeAPI()
        remove_track(api, "pl1", "spotify:track:ccc", 2)
        kinds = [call[0] for call in api.calls]
        self.assertEqual(kinds, ["playlist", "items", "remove"])
        self.assertEqual(api.calls[1], ("items", "pl1", 50, 0))
        self.assertEqual(api.calls[2], (
            "remove",
            "pl1",
            ["spotify:track:ccc"],
            "snap",
            [2],
        ))

    def test_remove_does_not_call_delete_when_the_row_changed(self):
        api = FakeAPI()
        with self.assertRaises(PlaylistEditorError):
            remove_track(api, "pl1", "spotify:track:aaa", 2)
        self.assertNotIn("remove", [call[0] for call in api.calls])

    def test_move_down_uses_insert_before_plus_two(self):
        api = FakeAPI(total=10)
        result = move_track(api, "pl1", 3, "down", uri="spotify:track:ddd")
        self.assertEqual(result["range_start"], 3)
        self.assertEqual(result["insert_before"], 5)
        self.assertEqual(result["range_length"], 1)
        reorder = api.calls[-1]
        self.assertEqual(reorder[0], "reorder")
        self.assertEqual(reorder[2:], (3, 5, 1, "snap"))

    def test_move_up_and_already_first(self):
        api = FakeAPI()
        move_track(api, "pl1", 1, "up")
        self.assertEqual(api.calls[-1][2:], (1, 0, 1, "snap"))
        api.calls.clear()
        with self.assertRaises(PlaylistEditorError):
            move_track(api, "pl1", 0, "up")
        self.assertEqual(api.calls, [("playlist", "pl1")])

    def test_spotify_error_message_is_kept(self):
        api = FakeAPI()

        def forbidden(playlist_id):
            return FakeResponse({"error": {"status": 403, "message": "Not the owner"}}, status=403)

        api.get_playlist = forbidden
        with self.assertRaises(PlaylistEditorError) as caught:
            playlist_detail(api, "pl1", 0)
        self.assertEqual(str(caught.exception), "Not the owner")
        self.assertEqual(caught.exception.status, 403)


class SpotifyPlaylistWriteTests(TestCase):
    def test_methods_hit_the_february_playlist_routes(self):
        api = SpotifyAPI(access_token="token")
        with patch(
            "player.spotify_api.requests.request",
            return_value=FakeResponse({"id": "pl1"}),
        ) as request:
            api.create_playlist("Night", description="Quiet", public=False)
            api.update_playlist_details("pl1", name="Dawn", description="Early")
            api.remove_playlist_from_library("pl1")
            api.get_playlist_items("pl1", limit=80, offset=50)
            api.add_playlist_items("pl1", ["spotify:track:aaa"])
            api.remove_playlist_items(
                "pl1",
                ["spotify:track:aaa"],
                snapshot_id="snap",
                positions=[2],
            )
            api.reorder_playlist_items(
                "pl1",
                range_start=3,
                insert_before=5,
                range_length=1,
                snapshot_id="snap",
            )

        calls = request.call_args_list
        methods = [call.args[0] for call in calls]
        urls = [call.args[1] for call in calls]
        self.assertEqual(methods, ["POST", "PUT", "DELETE", "GET", "POST", "DELETE", "PUT"])
        self.assertTrue(urls[0].endswith("/me/playlists"))
        self.assertEqual(calls[0].kwargs["json"], {
            "name": "Night",
            "description": "Quiet",
            "public": False,
        })
        self.assertTrue(urls[1].endswith("/playlists/pl1"))
        self.assertEqual(calls[1].kwargs["json"], {"name": "Dawn", "description": "Early"})
        self.assertNotIn("public", calls[1].kwargs["json"])
        self.assertTrue(urls[2].endswith("/playlists/pl1/followers"))
        self.assertTrue(urls[3].endswith("/playlists/pl1/items"))
        self.assertEqual(calls[3].kwargs["params"], {"limit": 50, "offset": 50})
        self.assertTrue(urls[4].endswith("/playlists/pl1/items"))
        self.assertEqual(calls[4].kwargs["json"], {"uris": ["spotify:track:aaa"]})
        self.assertTrue(urls[5].endswith("/playlists/pl1/items"))
        self.assertEqual(calls[5].kwargs["json"], {
            "items": [{"uri": "spotify:track:aaa", "positions": [2]}],
            "snapshot_id": "snap",
        })
        self.assertTrue(urls[6].endswith("/playlists/pl1/items"))
        self.assertEqual(calls[6].kwargs["json"], {
            "range_start": 3,
            "insert_before": 5,
            "range_length": 1,
            "snapshot_id": "snap",
        })
        self.assertNotIn("uris", calls[6].kwargs["json"])
        joined = " ".join(urls)
        self.assertNotIn("/recommendations", joined)
        self.assertNotIn("audio-features", joined)
        self.assertNotIn("/browse/", joined)
        self.assertNotIn("/tracks?", joined)


class PlaylistEditorViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_endpoints_require_a_session(self):
        response = self.client.get("/playlist-editor/playlists/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")

    @patch("player.features.playlist_editor.views.get_spotify_api")
    def test_create_rename_move_and_delete_through_the_views(self, get_api):
        api = FakeAPI(total=10)
        get_api.return_value = api

        created = self.client.post(
            "/playlist-editor/create/",
            data=json.dumps({"name": "Night", "description": "Quiet", "public": True}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["id"], "new1")
        self.assertFalse(created.json()["public"])
        self.assertEqual(api.calls[0], ("create", "Night", "Quiet", False))

        renamed = self.client.post(
            "/playlist-editor/pl1/details/",
            data=json.dumps({"name": "Dawn"}),
            content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["name"], "Dawn")

        moved = self.client.post(
            "/playlist-editor/pl1/items/move/",
            data=json.dumps({
                "index": 3,
                "direction": "down",
                "uri": "spotify:track:ddd",
            }),
            content_type="application/json",
        )
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["insert_before"], 5)
        self.assertEqual(moved.json()["range_length"], 1)

        removed = self.client.post("/playlist-editor/pl1/library/")
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.json()["removed"])
        self.assertIn(("unfollow", "pl1"), api.calls)

    @patch("player.features.playlist_editor.views.get_spotify_api")
    def test_bad_json_and_scope_stays_private(self, get_api):
        get_api.return_value = FakeAPI()
        response = self.client.post(
            "/playlist-editor/create/",
            data="{",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

        from player.views import SPOTIFY_SCOPE
        self.assertIn("playlist-modify-private", SPOTIFY_SCOPE)
        self.assertNotIn("playlist-modify-public", SPOTIFY_SCOPE)


class PlaylistEditorPageTests(TestCase):
    def test_player_page_has_one_playlists_editor_tab(self):
        import time

        from player.models import SpotifyAccount

        account = SpotifyAccount.objects.create(
            spotify_user_id="editor-user",
            display_name="Editor",
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
        self.assertEqual(body.count('id="tab-playlist-editor"'), 1)
        self.assertIn(">Playlists editor</button>", body)
        self.assertEqual(body.count('id="content-playlist-editor"'), 1)
        self.assertIn("Create private playlist", body)
        self.assertIn("playlist_editor/editor.css", body)
        self.assertIn('id="tab-feel"', body)
        self.assertIn("Remove from library", body)
        self.assertIn("spotify:track:", body)
