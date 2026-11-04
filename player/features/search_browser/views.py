"""HTTP entry for the search browser. One search per request that has a query."""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from player.features.search_browser.browse import search_page
from player.features.search_browser.query import (
    SESSION_MARKET_KEY,
    SearchBrowserError,
    normalize_market,
)
from player.spotify_api import get_spotify_api


def _store_market(request, market):
    if market:
        request.session[SESSION_MARKET_KEY] = market
    else:
        request.session.pop(SESSION_MARKET_KEY, None)


@require_http_methods(["GET"])
def search_browser(request):
    """
    GET /search-browser/

    With q, type, and offset: one Spotify search.
    With only market: remember the country on the session and do not search.
    """
    api = get_spotify_api(request)
    if not api:
        return JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )

    try:
        if "market" in request.GET:
            market = normalize_market(request.GET.get("market"))
            _store_market(request, market)
        else:
            market = normalize_market(request.session.get(SESSION_MARKET_KEY, ""))
    except SearchBrowserError as exc:
        return JsonResponse({"error": str(exc), "code": exc.code}, status=400)

    query = request.GET.get("q", "")
    if not str(query or "").strip():
        return JsonResponse({"market": market, "searched": False, "reads": []})

    try:
        page = search_page(
            api,
            q=query,
            type=request.GET.get("type", "track"),
            limit=request.GET.get("limit", 10),
            offset=request.GET.get("offset", 0),
            market=market,
        )
    except SearchBrowserError as exc:
        return JsonResponse({"error": str(exc), "code": exc.code}, status=400)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    page["searched"] = True
    return JsonResponse(page)
