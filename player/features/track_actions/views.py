import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

from .actions import add_track_to_playlist, save_track, save_uri


def _payload(request):
    """JSON body, with query or form fields filling anything left blank."""
    data = {}
    content_type = request.content_type or ""
    if request.body and "json" in content_type:
        try:
            parsed = json.loads(request.body.decode() or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None
        data.update(parsed)
    for key in ("id", "uri", "playlist_id", "track_id"):
        if data.get(key):
            continue
        value = request.POST.get(key) or request.GET.get(key)
        if value:
            data[key] = value
    return data


def _spotify_error(response):
    status = getattr(response, "status_code", "")
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return error["message"]
        if isinstance(error, str):
            return error
    return f"Spotify API error: {status}"


def _api_or_401(request):
    api = get_spotify_api(request)
    if not api:
        return None, JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    return api, None


def _spotify_result(response):
    status = getattr(response, "status_code", 500)
    if status == 401:
        return JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    if status >= 400:
        return JsonResponse({"error": _spotify_error(response)}, status=400)
    return None


@csrf_exempt
@require_http_methods(["POST"])
def save_track_view(request):
    """Save one track with PUT /me/library?uris=spotify:track:{id}."""
    api, error = _api_or_401(request)
    if error:
        return error
    data = _payload(request)
    if data is None:
        return JsonResponse({"error": "Expected JSON"}, status=400)
    raw = data.get("uri") or data.get("id") or data.get("track_id") or ""
    try:
        result = save_track(api, raw)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    failed = _spotify_result(result["response"])
    if failed:
        return failed
    return JsonResponse({"status": "saved", "uri": result["uri"]})


@csrf_exempt
@require_http_methods(["POST"])
def add_to_playlist_view(request):
    """Add one URI with a single POST /playlists/{id}/items."""
    api, error = _api_or_401(request)
    if error:
        return error
    data = _payload(request)
    if data is None:
        return JsonResponse({"error": "Expected JSON"}, status=400)
    playlist_id = data.get("playlist_id") or ""
    uri = data.get("uri") or data.get("id") or data.get("track_id") or ""
    try:
        response = add_track_to_playlist(api, playlist_id, uri)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    failed = _spotify_result(response)
    if failed:
        return failed
    raw = str(uri).strip()
    added_uri = raw if raw.startswith("spotify:") else save_uri(raw)
    return JsonResponse({
        "status": "added",
        "playlist_id": str(playlist_id).strip(),
        "uri": added_uri,
    })
