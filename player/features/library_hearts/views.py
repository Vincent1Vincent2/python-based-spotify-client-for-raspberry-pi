"""HTTP API for the Liked Songs / saved-album hearts."""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

from .library import LibraryError, contains, remove, save


def _api_or_error(request):
    api = get_spotify_api(request)
    if not api:
        return None, JsonResponse(
            {'error': 'Not authenticated', 'code': 'token_expired'},
            status=401,
        )
    return api, None


def _json_error(exc):
    if exc.code == 'needs_scope':
        status = 403
    elif exc.code == 'token_expired':
        status = 401
    else:
        status = 400
    return JsonResponse({'error': str(exc), 'code': exc.code}, status=status)


def _uris_from_request(request):
    uris = request.GET.get('uris')
    if uris:
        return uris
    if not request.body:
        return ''
    try:
        payload = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get('uris') is not None:
        return payload.get('uris')
    if payload.get('uri'):
        return payload.get('uri')
    return ''


@require_http_methods(['GET'])
def contains_view(request):
    """Check saved tracks and albums with one library contains call."""
    api, error = _api_or_error(request)
    if error:
        return error
    uris = _uris_from_request(request)
    if uris is None:
        return JsonResponse({'error': 'Expected JSON', 'code': 'library_error'}, status=400)
    try:
        return JsonResponse(contains(api, uris))
    except LibraryError as exc:
        return _json_error(exc)


@csrf_exempt
@require_http_methods(['PUT', 'DELETE'])
def items_view(request):
    """Save with PUT /me/library?uris= or remove with DELETE /me/library?uris=."""
    api, error = _api_or_error(request)
    if error:
        return error
    uris = _uris_from_request(request)
    if uris is None:
        return JsonResponse({'error': 'Expected JSON', 'code': 'library_error'}, status=400)
    action = remove if request.method == 'DELETE' else save
    try:
        return JsonResponse(action(api, uris))
    except LibraryError as exc:
        return _json_error(exc)
