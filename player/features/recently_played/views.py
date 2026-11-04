from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

from .recently import (
    LOGIN_PATH,
    NeedsScope,
    RecentlyPlayedError,
    load_recently_played,
    play_recent,
)


def _api_or_401(request):
    api = get_spotify_api(request)
    if not api:
        return None, JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    return api, None


def _error(exc):
    body = {"error": str(exc), "code": exc.code}
    if isinstance(exc, NeedsScope):
        body["login"] = LOGIN_PATH
    return JsonResponse(body, status=exc.status)


def _device_id(request):
    device_id = None
    if request.session.get("use_web_player", True):
        device_id = request.GET.get("device_id") or None
    if not device_id:
        device_id = request.session.get("selected_device_id")
    return device_id


@require_http_methods(["GET"])
def recently_played_view(request):
    """GET /me/player/recently-played?limit=50, then the rows."""
    api, error = _api_or_401(request)
    if error:
        return error
    try:
        items = load_recently_played(api)
    except RecentlyPlayedError as exc:
        return _error(exc)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"items": items})


@csrf_exempt
@require_http_methods(["POST"])
def play_recently_played_view(request):
    """start_playback(uris=[the row uri])."""
    api, error = _api_or_401(request)
    if error:
        return error
    try:
        result = play_recent(
            api,
            request.GET.get("uri", ""),
            device_id=_device_id(request),
        )
    except RecentlyPlayedError as exc:
        return _error(exc)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(result)
