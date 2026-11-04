"""Build one Spotify search. Limit never goes above 10."""

import re

MAX_LIMIT = 10
SEARCH_TYPES = ("track", "album", "artist", "playlist", "show", "episode")
SESSION_MARKET_KEY = "search_browser_market"
_MARKET = re.compile(r"^[A-Za-z]{2}$")
_QUERY_MAX = 250


class SearchBrowserError(ValueError):
    def __init__(self, message, code="bad_query"):
        super().__init__(message)
        self.code = code


def normalize_market(market):
    """Optional ISO 3166-1 alpha-2 code. Blank means no market."""
    if market is None:
        return None
    text = str(market).strip()
    if not text:
        return None
    if not _MARKET.fullmatch(text):
        raise SearchBrowserError(
            "Market must be a two-letter country code.",
            code="bad_market",
        )
    return text.upper()


def _parse_type(type_name):
    chosen = str(type_name or "").strip().lower()
    if chosen not in SEARCH_TYPES:
        allowed = ", ".join(SEARCH_TYPES)
        raise SearchBrowserError(
            f"Type must be one of: {allowed}.",
            code="bad_type",
        )
    return chosen


def _parse_limit(limit):
    if limit is None or limit == "":
        return MAX_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError):
        raise SearchBrowserError("Limit must be a whole number.", code="bad_limit")
    if value < 1:
        raise SearchBrowserError("Limit must be at least 1.", code="bad_limit")
    if value > MAX_LIMIT:
        return MAX_LIMIT
    return value


def _parse_offset(offset):
    if offset is None or offset == "":
        return 0
    try:
        value = int(offset)
    except (TypeError, ValueError):
        raise SearchBrowserError("Offset must be a whole number.", code="bad_offset")
    if value < 0:
        raise SearchBrowserError("Offset must be zero or greater.", code="bad_offset")
    return value


def build_search_query(q, type, limit=MAX_LIMIT, offset=0, market=None):
    """
    Arguments for SpotifyAPI.search.

    `type` is a single catalog type. `limit` is clamped to 1..10.
    `offset` is always present. `market` is included only when set.
    """
    text = str(q or "").strip()
    if not text:
        raise SearchBrowserError("Query is required.", code="bad_query")
    if len(text) > _QUERY_MAX:
        raise SearchBrowserError("Query is too long.", code="bad_query")

    built = {
        "q": text,
        "type": _parse_type(type),
        "limit": _parse_limit(limit),
        "offset": _parse_offset(offset),
    }
    if built["limit"] > MAX_LIMIT:
        built["limit"] = MAX_LIMIT

    code = normalize_market(market)
    if code:
        built["market"] = code
    return built
