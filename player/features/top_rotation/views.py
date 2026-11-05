"""HTTP actions for heavy rotation. Each view performs one Spotify read."""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from player.spotify_api import get_spotify_api

from .rotation import TopRotationError, TopScopeError, load_top


@require_GET
def top_tracks(request):
    """GET /me/top/tracks?limit=10&time_range=..."""
    return _respond(request, "tracks")


@require_GET
def top_artists(request):
    """GET /me/top/artists?limit=10&time_range=..."""
    return _respond(request, "artists")


def _respond(request, kind):
    api = get_spotify_api(request)
    if api is None:
        return JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    try:
        payload = load_top(api, kind, request.GET.get("time_range"))
    except TopScopeError as exc:
        return JsonResponse(
            {"error": str(exc), "code": exc.code, "link": exc.link},
            status=403,
        )
    except TopRotationError as exc:
        return JsonResponse({"error": str(exc), "code": exc.code}, status=400)
    return JsonResponse(payload)
