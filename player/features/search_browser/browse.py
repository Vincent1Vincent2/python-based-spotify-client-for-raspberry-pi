"""Run one catalog search and shape the page. Does not follow `next`."""

from urllib.parse import quote

from player.features.search_browser.query import build_search_query

_RESULT_KEY = {
    "track": "tracks",
    "album": "albums",
    "artist": "artists",
    "playlist": "playlists",
    "show": "shows",
    "episode": "episodes",
}

_DETAIL_ROUTES = {
    "album": "/album-detail/?id=",
    "playlist": "/playlist-detail/?id=",
}


def search_page(api, q, type, limit=10, offset=0, market=None):
    """One call to SpotifyAPI.search. The next page is another call."""
    built = build_search_query(q, type, limit=limit, offset=offset, market=market)
    response = api.search(**built)
    response.raise_for_status()
    payload = response.json() or {}
    page = _page_from_payload(built, payload)
    page["reads"] = ["GET /search"]
    return page


def _page_from_payload(built, payload):
    key = _RESULT_KEY[built["type"]]
    paging = payload.get(key) or {}
    if not isinstance(paging, dict):
        paging = {}
    raw_items = paging.get("items") or []
    if not isinstance(raw_items, list):
        raw_items = []

    items = []
    for raw in raw_items:
        item = _item(built["type"], raw)
        if item:
            items.append(item)

    has_next = bool(paging.get("next"))
    offset = built["offset"]
    limit = built["limit"]
    return {
        "q": built["q"],
        "type": built["type"],
        "limit": limit,
        "offset": offset,
        "market": built.get("market"),
        "total": paging.get("total") or 0,
        "has_next": has_next,
        "next_offset": offset + limit if has_next else None,
        "prev_offset": max(0, offset - limit) if offset else None,
        "items": items,
    }


def _item(type_name, raw):
    if not isinstance(raw, dict):
        return None
    item_id = raw.get("id")
    if not item_id:
        return None
    item_id = str(item_id)
    detail = _DETAIL_ROUTES.get(type_name)
    shaped = {
        "id": item_id,
        "type": type_name,
        "name": raw.get("name") or "",
        "uri": raw.get("uri") or "",
        "subtitle": _subtitle(type_name, raw),
        "image": _image(raw, type_name),
        "detail_url": f"{detail}{quote(item_id, safe='')}" if detail else None,
    }
    if raw.get("duration_ms"):
        shaped["duration_ms"] = raw.get("duration_ms")
    return shaped


def _image(raw, type_name):
    images = raw.get("images")
    if type_name == "track":
        album = raw.get("album") or {}
        images = album.get("images")
    return _first_url(images)


def _first_url(images):
    if not isinstance(images, list):
        return None
    for image in images:
        if isinstance(image, dict) and image.get("url"):
            return image["url"]
    return None


def _join_names(entries):
    if not isinstance(entries, list):
        return ""
    names = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name"):
            names.append(entry["name"])
    return ", ".join(names)


def _subtitle(type_name, raw):
    if type_name == "track":
        album = (raw.get("album") or {}).get("name") or ""
        return _dot(_join_names(raw.get("artists")), album)
    if type_name == "album":
        kind = (raw.get("album_type") or "album").replace("_", " ")
        total = raw.get("total_tracks")
        count = f"{total} tracks" if total else ""
        return _dot(_join_names(raw.get("artists")), kind.capitalize(), count)
    if type_name == "artist":
        genres = raw.get("genres") or []
        if isinstance(genres, list) and genres:
            return ", ".join(str(genre) for genre in genres[:3])
        return "Artist"
    if type_name == "playlist":
        owner = raw.get("owner") or {}
        owner_name = ""
        if isinstance(owner, dict):
            owner_name = owner.get("display_name") or owner.get("id") or ""
        tracks = raw.get("tracks") or {}
        total = tracks.get("total") if isinstance(tracks, dict) else None
        count = f"{total} tracks" if total is not None else ""
        return _dot(owner_name, count)
    if type_name == "show":
        episodes = raw.get("total_episodes")
        count = f"{episodes} episodes" if episodes else ""
        return _dot(raw.get("publisher") or "", count)
    if type_name == "episode":
        show = raw.get("show") or {}
        show_name = show.get("name") if isinstance(show, dict) else ""
        return show_name or "Episode"
    return ""


def _dot(*parts):
    return " • ".join(part for part in parts if part)
