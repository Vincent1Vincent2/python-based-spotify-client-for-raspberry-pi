"""Paged catalog search. One Spotify search per user action."""

from player.features.search_browser.browse import search_page
from player.features.search_browser.query import MAX_LIMIT, SEARCH_TYPES, build_search_query

__all__ = ["MAX_LIMIT", "SEARCH_TYPES", "build_search_query", "search_page"]
