"""JSON endpoints for the playlist editor. No Spotify calls happen at import."""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

from .service import (
    PlaylistEditorError,
    add_track,
    create_private_playlist,
    list_playlists,
    move_track,
    playlist_detail,
    remove_from_library,
    remove_track,
    update_playlist,
)

logger = logging.getLogger(__name__)


def _json_body(request):
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _editor_error(exc):
    return JsonResponse({"error": str(exc), "code": exc.code}, status=exc.status)


def _call(request, action):
    api = get_spotify_api(request)
    if not api:
        return JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    try:
        return JsonResponse(action(api))
    except PlaylistEditorError as exc:
        return _editor_error(exc)
    except Exception as exc:
        logger.warning("playlist editor request failed", exc_info=True)
        return JsonResponse({"error": str(exc), "code": "playlist_editor"}, status=400)


@csrf_exempt
@require_http_methods(["GET"])
def playlists_view(request):
    """One page of the current user's playlists. Page size is 50."""
    return _call(request, lambda api: list_playlists(api, request.GET.get("offset", 0)))


@csrf_exempt
@require_http_methods(["POST"])
def create_view(request):
    """Create a private playlist. public is always false."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON.", "code": "playlist_editor"}, status=400)

    def action(api):
        return create_private_playlist(
            api,
            payload.get("name"),
            payload.get("description", ""),
        )

    return _call(request, action)


@csrf_exempt
@require_http_methods(["GET"])
def detail_view(request, playlist_id):
    """Playlist name, description, and one page of items."""
    return _call(
        request,
        lambda api: playlist_detail(api, playlist_id, request.GET.get("offset", 0)),
    )


@csrf_exempt
@require_http_methods(["POST"])
def update_view(request, playlist_id):
    """Change the name, the description, or both."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON.", "code": "playlist_editor"}, status=400)
    fields = [key for key in ("name", "description") if key in payload]

    def action(api):
        return update_playlist(
            api,
            playlist_id,
            name=payload.get("name"),
            description=payload.get("description"),
            fields=fields,
        )

    return _call(request, action)


@csrf_exempt
@require_http_methods(["POST"])
def remove_library_view(request, playlist_id):
    """Remove a private playlist from the current user's library."""
    return _call(request, lambda api: remove_from_library(api, playlist_id))


@csrf_exempt
@require_http_methods(["POST"])
def add_view(request, playlist_id):
    """Append one track URI."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON.", "code": "playlist_editor"}, status=400)
    return _call(request, lambda api: add_track(api, playlist_id, payload.get("uri")))


@csrf_exempt
@require_http_methods(["POST"])
def remove_item_view(request, playlist_id):
    """Remove the track at one position."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON.", "code": "playlist_editor"}, status=400)

    def action(api):
        return remove_track(api, playlist_id, payload.get("uri"), payload.get("index"))

    return _call(request, action)


@csrf_exempt
@require_http_methods(["POST"])
def move_view(request, playlist_id):
    """Move one track up or down."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON.", "code": "playlist_editor"}, status=400)

    def action(api):
        return move_track(
            api,
            playlist_id,
            payload.get("index"),
            (payload.get("direction") or "").strip().lower(),
            uri=payload.get("uri") or None,
        )

    return _call(request, action)
