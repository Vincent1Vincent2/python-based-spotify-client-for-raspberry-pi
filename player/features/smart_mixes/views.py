"""HTTP entry for smart mixes. The filter and playlist work live next door."""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_active_account, get_spotify_api

from .filter import parse_year_from
from .mix import SmartMixError, SmartMixScopeError, build_smart_mix


def _json_body(request):
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _text(value):
    return value if isinstance(value, str) else ""


def playback_device(request, explicit):
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if request.session.get("use_web_player"):
        return request.session.get("web_player_device_id") or None
    return request.session.get("selected_device_id") or None


@csrf_exempt
@require_http_methods(["POST"])
def smart_mix_view(request):
    """
    Build a smart mix and play it.
    Spotify: GET /me/tracks?limit=50, then POST /me/playlists and one POST items.
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
    try:
        year_from = parse_year_from(payload.get("year_from"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc), "code": "bad_year"}, status=400)

    device_id = playback_device(request, payload.get("device_id"))
    if not device_id:
        if request.session.get("use_web_player"):
            message = "The browser player is still connecting. Try again in a moment."
        else:
            message = "No device selected"
        return JsonResponse({"error": message, "code": "no_device"}, status=400)

    try:
        result = build_smart_mix(
            api,
            request.session,
            account.spotify_user_id,
            artist=_text(payload.get("artist")),
            title=_text(payload.get("title")),
            year_from=year_from,
            device_id=device_id,
        )
    except SmartMixError as exc:
        status = 403 if isinstance(exc, SmartMixScopeError) else 400
        return JsonResponse({"error": str(exc), "code": exc.code}, status=status)
    return JsonResponse(result)
