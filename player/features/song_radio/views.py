"""POST the seed track. The radio module does the Spotify calls."""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_active_account, get_spotify_api

from .radio import SongRadioError, SongRadioScopeError, start_song_radio


def _json_body(request):
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def playback_device(request, explicit):
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if request.session.get("use_web_player"):
        return request.session.get("web_player_device_id")
    return request.session.get("selected_device_id")


def _error(exc):
    status = 403 if isinstance(exc, SongRadioScopeError) else 400
    return JsonResponse({"error": str(exc), "code": exc.code}, status=status)


@csrf_exempt
@require_http_methods(["POST"])
def song_radio_view(request):
    """
    Build a song radio from the posted seed and play it.

    The seed is name, artists, uri, and album_id when the client has one.
    Spotify is not asked which song is playing: that would be a third read.
    """
    api = get_spotify_api(request)
    account = get_active_account(request)
    if not api or not account:
        return JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Expected JSON"}, status=400)
    device_id = playback_device(request, payload.get("device_id"))
    if not device_id:
        if request.session.get("use_web_player"):
            message = "The browser player is still connecting. Try again in a moment."
        else:
            message = "No device selected"
        return JsonResponse({"error": message, "code": "no_device"}, status=400)
    try:
        result = start_song_radio(api, payload, device_id)
    except SongRadioError as exc:
        return _error(exc)
    return JsonResponse(result)
