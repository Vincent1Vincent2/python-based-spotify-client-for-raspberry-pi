"""Home tab endpoint. One Spotify read, then the rows."""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api

from .home import LOGIN_URL, LibraryHomeError, LibraryHomeScopeError, load_home


@require_http_methods(["GET"])
def home(request):
    """
    Short home strip.

    Spotify read: GET /me/player/recently-played?limit=10.
    A 403 from that read is needs_scope, and the client reconnects
    at /login/?auth=1. Query limits are ignored so this cannot ask
    Spotify for more than 10.
    """
    api = get_spotify_api(request)
    if not api:
        return JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    try:
        payload = load_home(api)
    except LibraryHomeScopeError as exc:
        return JsonResponse(
            {
                "error": str(exc),
                "code": "needs_scope",
                "login_url": LOGIN_URL,
            },
            status=403,
        )
    except LibraryHomeError as exc:
        return JsonResponse(
            {"error": str(exc), "code": exc.code},
            status=exc.status,
        )
    return JsonResponse(payload)
