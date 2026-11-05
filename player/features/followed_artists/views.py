from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

from .following import (
    LOGIN_PATH,
    FollowedArtistsError,
    NeedsScope,
    load_followed_artists,
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


@require_http_methods(["GET"])
def followed_artists_view(request):
    """GET /me/following?type=artist&limit=50, then name and image."""
    api, error = _api_or_401(request)
    if error:
        return error
    try:
        artists = load_followed_artists(api)
    except FollowedArtistsError as exc:
        return _error(exc)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"artists": artists})
