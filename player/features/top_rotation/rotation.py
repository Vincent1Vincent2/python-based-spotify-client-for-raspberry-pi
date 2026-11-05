"""
Heavy rotation.

Two lists, each a single Spotify read:

    GET /me/top/tracks?limit=10&time_range=medium_term
    GET /me/top/artists?limit=10&time_range=medium_term

A range control may be short_term, medium_term, or long_term. That value
is sent on the one list being reloaded. The limit stays at 10. Items are
shown as they arrived. This module does not call any other Spotify path.
"""

TOP_LIMIT = 10
DEFAULT_TIME_RANGE = "medium_term"
TIME_RANGES = ("short_term", "medium_term", "long_term")
LOGIN_LINK = "/login/?auth=1"

_ENDPOINTS = {
    "tracks": "me/top/tracks",
    "artists": "me/top/artists",
}


class TopRotationError(Exception):
    def __init__(self, message, code="rotation_error"):
        super().__init__(message)
        self.code = code


class TopScopeError(TopRotationError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify to read your heavy rotation.",
            code="needs_scope",
        )
        self.link = LOGIN_LINK


def normalize_time_range(value):
    """Keep a known range as given. Anything else is the six-month list."""
    if isinstance(value, str):
        value = value.strip()
    if value in TIME_RANGES:
        return value
    return DEFAULT_TIME_RANGE


def load_top(api, kind, time_range=DEFAULT_TIME_RANGE):
    """Read one top list. ``kind`` is ``tracks`` or ``artists``."""
    endpoint = _ENDPOINTS.get(kind)
    if endpoint is None:
        raise TopRotationError("Choose top tracks or top artists.")

    time_range = normalize_time_range(time_range)
    params = {"limit": TOP_LIMIT, "time_range": time_range}
    if params["limit"] > 10:
        params["limit"] = 10

    response = api.get(endpoint, params=params)
    body = _body(response)
    present = _public_track if kind == "tracks" else _public_artist
    items = []
    raw_items = body.get("items") if isinstance(body.get("items"), list) else []
    for item in raw_items:
        if len(items) >= TOP_LIMIT:
            break
        if isinstance(item, dict):
            items.append(present(item))

    return {
        "kind": kind,
        "time_range": time_range,
        "items": items,
        "reads": [f"GET /{endpoint}?limit={params['limit']}&time_range={time_range}"],
    }


def _body(response):
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise TopScopeError()
    if status >= 400:
        raise TopRotationError(f"Spotify could not return that list ({status}).")
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _names(value):
    names = []
    for entry in value or []:
        if isinstance(entry, dict):
            name = entry.get("name") or ""
        else:
            name = str(entry or "")
        if name:
            names.append(name)
    return names


def _image(images):
    if not isinstance(images, list) or not images:
        return ""
    first = images[0]
    if isinstance(first, dict):
        return first.get("url") or ""
    return ""


def _public_track(item):
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    return {
        "id": item.get("id") or "",
        "uri": item.get("uri") or "",
        "name": item.get("name") or "",
        "artists": _names(item.get("artists")),
        "album": album.get("name") or "",
        "image": _image(album.get("images")),
    }


def _public_artist(item):
    genres = item.get("genres") if isinstance(item.get("genres"), list) else []
    return {
        "id": item.get("id") or "",
        "uri": item.get("uri") or "",
        "name": item.get("name") or "",
        "genres": [str(genre) for genre in genres if genre],
        "image": _image(item.get("images")),
    }
