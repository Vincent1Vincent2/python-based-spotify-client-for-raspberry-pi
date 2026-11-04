"""Shuffle, repeat, and volume for the active player."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

REPEAT_STATES = ('off', 'context', 'track')


def _api(request):
    api = get_spotify_api(request)
    if not api:
        return None, JsonResponse(
            {'error': 'Not authenticated', 'code': 'token_expired'},
            status=401,
        )
    return api, None


def _device_id(request):
    """Same target as seek: the selected device, or the active one for the web player."""
    if request.session.get('use_web_player', True):
        return None
    return request.session.get('selected_device_id')


def _finish(response, payload):
    if response.status_code >= 400:
        return JsonResponse({
            'error': f'Spotify API error: {response.status_code}',
            'code': 'playback_error',
        }, status=502)
    return JsonResponse(payload)


@csrf_exempt
@require_http_methods(["POST"])
def shuffle(request):
    """PUT /me/player/shuffle?state=true|false."""
    state = request.GET.get('state', '')
    if state not in ('true', 'false'):
        return JsonResponse({'error': 'state must be true or false'}, status=400)

    api, error = _api(request)
    if error:
        return error
    try:
        response = api.set_shuffle(state == 'true', device_id=_device_id(request))
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return _finish(response, {'status': 'shuffle', 'state': state == 'true'})


@csrf_exempt
@require_http_methods(["POST"])
def repeat(request):
    """PUT /me/player/repeat?state=off|track|context."""
    state = request.GET.get('state', '')
    if state not in REPEAT_STATES:
        return JsonResponse({'error': 'state must be off, track, or context'}, status=400)

    api, error = _api(request)
    if error:
        return error
    try:
        response = api.set_repeat(state, device_id=_device_id(request))
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return _finish(response, {'status': 'repeat', 'state': state})


@csrf_exempt
@require_http_methods(["POST"])
def volume(request):
    """PUT /me/player/volume?volume_percent=0-100."""
    raw = request.GET.get('volume_percent', '')
    if raw == '':
        return JsonResponse({'error': 'volume_percent required'}, status=400)
    try:
        volume_percent = int(raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'volume_percent must be an integer'}, status=400)
    if volume_percent < 0 or volume_percent > 100:
        return JsonResponse({'error': 'volume_percent must be between 0 and 100'}, status=400)

    api, error = _api(request)
    if error:
        return error
    try:
        response = api.set_volume(volume_percent, device_id=_device_id(request))
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return _finish(response, {'status': 'volume', 'volume_percent': volume_percent})
