"""Local playlist pins and tags for the account active on this kiosk."""

import json
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.template.loader import get_template, render_to_string
from django.test import Client, SimpleTestCase, TestCase
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.models import PlaylistMark, SpotifyAccount
from player.spotify_api import get_active_account


def _json_body(request):
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _active_account(request):
    account = get_active_account(request)
    if account is None:
        return None, JsonResponse({"error": "Not authenticated"}, status=401)
    return account, None


def _playlist_id(payload):
    raw = payload.get("playlist_id", "")
    if not isinstance(raw, str):
        return None
    playlist_id = raw.strip()
    max_length = PlaylistMark._meta.get_field("playlist_id").max_length
    if not playlist_id or len(playlist_id) > max_length:
        return None
    return playlist_id


def serialize_mark(mark):
    return {
        "playlist_id": mark.playlist_id,
        "pinned": mark.pinned,
        "tag": mark.tag,
    }


@csrf_exempt
@require_http_methods(["POST"])
def pin_playlist(request):
    """Pin or unpin a playlist for the active account. No Spotify call."""
    account, error = _active_account(request)
    if error:
        return error
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON"}, status=400)
    playlist_id = _playlist_id(payload)
    if playlist_id is None:
        return JsonResponse({"error": "Playlist id required"}, status=400)
    if "pinned" in payload:
        pinned = payload["pinned"]
        if not isinstance(pinned, bool):
            return JsonResponse({"error": "Pinned must be true or false"}, status=400)
    else:
        pinned = True
    mark, _created = PlaylistMark.objects.update_or_create(
        account=account,
        playlist_id=playlist_id,
        defaults={"pinned": pinned},
    )
    return JsonResponse(serialize_mark(mark))


@csrf_exempt
@require_http_methods(["POST"])
def tag_playlist(request):
    """Save a local tag on a playlist for the active account. No Spotify call."""
    account, error = _active_account(request)
    if error:
        return error
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON"}, status=400)
    playlist_id = _playlist_id(payload)
    if playlist_id is None:
        return JsonResponse({"error": "Playlist id required"}, status=400)
    if "tag" not in payload or not isinstance(payload["tag"], str):
        return JsonResponse({"error": "Tag required"}, status=400)
    tag = payload["tag"].strip()
    max_length = PlaylistMark._meta.get_field("tag").max_length
    if len(tag) > max_length:
        return JsonResponse({"error": "Tag is too long"}, status=400)
    mark, _created = PlaylistMark.objects.update_or_create(
        account=account,
        playlist_id=playlist_id,
        defaults={"tag": tag},
    )
    return JsonResponse(serialize_mark(mark))


@csrf_exempt
@require_http_methods(["GET"])
def playlist_marks(request):
    """Pins and tags stored for the active account. No Spotify call."""
    account, error = _active_account(request)
    if error:
        return error
    marks = PlaylistMark.objects.filter(account=account)
    return JsonResponse({"marks": [serialize_mark(mark) for mark in marks]})


def _account(spotify_user_id, display_name):
    return SpotifyAccount.objects.create(
        spotify_user_id=spotify_user_id,
        display_name=display_name,
        access_token="access",
        refresh_token="refresh",
        token_expires_at=0,
    )


class PlaylistPinTests(TestCase):
    def setUp(self):
        self.ada = _account("ada", "Ada")
        self.bea = _account("bea", "Bea")
        self.client = Client()
        self.spotify = patch(
            "player.spotify_api.requests.request",
            side_effect=AssertionError("playlist marks must not call Spotify"),
        )
        self.spotify.start()
        self.addCleanup(self.spotify.stop)

    def activate(self, account):
        session = self.client.session
        session["active_account_id"] = account.id
        session.save()

    def post_json(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_pin_then_unpin(self):
        self.activate(self.ada)
        pinned = self.post_json(
            "/playlist-pins/pin/",
            {"playlist_id": "morning", "pinned": True},
        )
        self.assertEqual(pinned.status_code, 200)
        self.assertEqual(
            pinned.json(),
            {"playlist_id": "morning", "pinned": True, "tag": ""},
        )
        mark = PlaylistMark.objects.get(account=self.ada, playlist_id="morning")
        self.assertTrue(mark.pinned)

        unpinned = self.post_json(
            "/playlist-pins/pin/",
            {"playlist_id": "morning", "pinned": False},
        )
        self.assertEqual(unpinned.status_code, 200)
        self.assertFalse(unpinned.json()["pinned"])
        mark.refresh_from_db()
        self.assertFalse(mark.pinned)
        self.assertEqual(mark.tag, "")

        listed = self.client.get("/playlist-pins/marks/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            listed.json()["marks"],
            [{"playlist_id": "morning", "pinned": False, "tag": ""}],
        )

    def test_tag_save(self):
        self.activate(self.ada)
        self.post_json("/playlist-pins/pin/", {"playlist_id": "morning", "pinned": True})
        saved = self.post_json(
            "/playlist-pins/tag/",
            {"playlist_id": "morning", "tag": "  focus  "},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(
            saved.json(),
            {"playlist_id": "morning", "pinned": True, "tag": "focus"},
        )
        mark = PlaylistMark.objects.get(account=self.ada, playlist_id="morning")
        self.assertEqual(mark.tag, "focus")
        self.assertTrue(mark.pinned)

        cleared = self.post_json(
            "/playlist-pins/tag/",
            {"playlist_id": "morning", "tag": "   "},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["tag"], "")
        mark.refresh_from_db()
        self.assertEqual(mark.tag, "")
        self.assertTrue(mark.pinned)

    def test_marks_are_per_account(self):
        self.activate(self.ada)
        self.post_json("/playlist-pins/pin/", {"playlist_id": "shared", "pinned": True})
        self.post_json("/playlist-pins/tag/", {"playlist_id": "shared", "tag": "ada"})

        self.activate(self.bea)
        bea_before = self.client.get("/playlist-pins/marks/")
        self.assertEqual(bea_before.status_code, 200)
        self.assertEqual(bea_before.json()["marks"], [])
        self.post_json("/playlist-pins/pin/", {"playlist_id": "shared", "pinned": False})
        self.post_json("/playlist-pins/tag/", {"playlist_id": "shared", "tag": "bea"})
        bea_marks = self.client.get("/playlist-pins/marks/").json()["marks"]
        self.assertEqual(
            bea_marks,
            [{"playlist_id": "shared", "pinned": False, "tag": "bea"}],
        )

        ada = PlaylistMark.objects.get(account=self.ada, playlist_id="shared")
        bea = PlaylistMark.objects.get(account=self.bea, playlist_id="shared")
        self.assertTrue(ada.pinned)
        self.assertEqual(ada.tag, "ada")
        self.assertFalse(bea.pinned)
        self.assertEqual(bea.tag, "bea")

        self.activate(self.ada)
        ada_marks = self.client.get("/playlist-pins/marks/").json()["marks"]
        self.assertEqual(
            ada_marks,
            [{"playlist_id": "shared", "pinned": True, "tag": "ada"}],
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PlaylistMark.objects.create(
                    account=self.ada,
                    playlist_id="shared",
                    pinned=False,
                    tag="dup",
                )

        anonymous = Client()
        denied = anonymous.get("/playlist-pins/marks/")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(PlaylistMark.objects.count(), 2)


class PlaylistMarkPageTests(SimpleTestCase):
    def test_pin_and_tag_field_are_included_once(self):
        html = render_to_string(
            "player/index.html",
            {
                "client_id": "client",
                "access_token": "token",
                "use_web_player": True,
                "devices": [],
                "accounts": [],
                "active_account": None,
                "selected_device_id": None,
            },
        )
        source = get_template("player/index.html").template.source
        self.assertEqual(source.count('{% include "player/_playlist_mark.html" %}'), 1)
        self.assertEqual(html.count('id="playlistMark"'), 1)
        self.assertEqual(html.count('id="playlistPin"'), 1)
        self.assertEqual(html.count('id="playlistTag"'), 1)
        self.assertRegex(html, r'id="playlistMark"[^>]*\bhidden\b')
        self.assertIn("decoratePlaylistMark", html)
        self.assertEqual(html.count("function decoratePlaylistMark"), 1)

    def test_partial_can_decorate_a_playlist_id(self):
        html = render_to_string(
            "player/_playlist_mark.html",
            {"playlist_id": "pl-42"},
        )
        self.assertIn('data-playlist-id="pl-42"', html)
        self.assertIn(">pl-42<", html)
        self.assertIn("Pin", html)
        self.assertIn('id="playlistTag"', html)
        self.assertNotRegex(html, r'id="playlistMark"[^>]*\bhidden\b')
