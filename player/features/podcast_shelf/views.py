import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

from .shelf import (
    PodcastShelfError,
    list_saved_shows,
    page_offset,
    play_episode,
    remove_show,
    save_show,
    show_detail,
)


def _api(request):
    api = get_spotify_api(request)
    if not api:
        return None, JsonResponse(
            {'error': 'Not authenticated', 'code': 'token_expired'},
            status=401,
        )
    return api, None


def _failure(exc):
    payload = {'error': str(exc), 'code': exc.code}
    if exc.code == 'needs_scope':
        payload['login'] = '/login/?auth=1'
    return JsonResponse(payload, status=exc.status)


def _run(request, func):
    api, error = _api(request)
    if error:
        return error
    try:
        return JsonResponse(func(api))
    except PodcastShelfError as exc:
        return _failure(exc)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


def _json_body(request):
    if not request.body or 'json' not in (request.content_type or ''):
        return {}
    try:
        payload = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _session_device(request):
    if request.session.get('use_web_player', True):
        return request.session.get('web_player_device_id') or None
    return request.session.get('selected_device_id') or None


def _device_id(request, payload):
    chosen = _text(request.GET.get('device_id'))
    if not chosen and isinstance(payload, dict):
        chosen = _text(payload.get('device_id'))
    return chosen or _session_device(request)


@require_http_methods(['GET'])
def shows(request):
    """Saved shows. One GET /me/shows?limit=50."""
    try:
        offset = page_offset(request.GET.get('offset', '0'))
    except PodcastShelfError as exc:
        return _failure(exc)
    return _run(request, lambda api: list_saved_shows(api, offset))


@require_http_methods(['GET'])
def show_detail_view(request):
    """One show and one page of its episodes."""
    try:
        offset = page_offset(request.GET.get('offset', '0'))
    except PodcastShelfError as exc:
        return _failure(exc)
    show_id = request.GET.get('id') or ''
    return _run(request, lambda api: show_detail(api, show_id, offset))


@csrf_exempt
@require_http_methods(['POST'])
def save_show_view(request):
    """Save one show. PUT /me/library?uris=spotify:show:{id}."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Expected JSON'}, status=400)
    raw = _text(payload.get('show')) or _text(payload.get('id')) or _text(request.GET.get('id'))
    return _run(request, lambda api: save_show(api, raw))


@csrf_exempt
@require_http_methods(['POST'])
def remove_show_view(request):
    """Remove one show. DELETE /me/library?uris=spotify:show:{id}."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Expected JSON'}, status=400)
    show_id = _text(payload.get('id')) or _text(request.GET.get('id'))
    return _run(request, lambda api: remove_show(api, show_id))


@csrf_exempt
@require_http_methods(['POST'])
def play_episode_view(request):
    """Play one episode. start_playback uris=[spotify:episode:...]."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Expected JSON'}, status=400)
    episode_id = _text(request.GET.get('id'))
    if not episode_id and isinstance(payload, dict):
        episode_id = _text(payload.get('id'))
    device_id = _device_id(request, payload)
    return _run(request, lambda api: play_episode(api, episode_id, device_id))
