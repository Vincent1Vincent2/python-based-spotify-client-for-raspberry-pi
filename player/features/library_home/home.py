"""
Home strip from one Spotify read.

GET /me/player/recently-played?limit=10

This is not the full recently-played history: no cursors, no next page,
and no recommendations. The Feel button on the tab does not call Spotify.
"""

RECENT_LIMIT = 10
RECENT_ENDPOINT = "me/player/recently-played"
LOGIN_URL = "/login/?auth=1"


class LibraryHomeError(Exception):
    def __init__(self, message, code="library_home_error", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class LibraryHomeScopeError(LibraryHomeError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify to show recently played songs.",
            code="needs_scope",
            status=403,
        )


def parse_recently_played(payload):
    """Turn a recently-played body into at most ten display rows."""
    rows = []
    for item in _items(payload):
        row = _row(item)
        if row is None:
            continue
        rows.append(row)
        if len(rows) >= RECENT_LIMIT:
            break
    return rows


def load_home(api):
    """
    One call: GET /me/player/recently-played?limit=10.

    The limit is fixed. A 403 means the token is missing
    user-read-recently-played.
    """
    if RECENT_LIMIT > 10:
        raise LibraryHomeError("Home never asks for more than 10 plays.")
    response = api.get(RECENT_ENDPOINT, params={"limit": RECENT_LIMIT})
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise LibraryHomeScopeError()
    if status == 401:
        raise LibraryHomeError(
            "Not authenticated",
            code="token_expired",
            status=401,
        )
    if status >= 400:
        raise LibraryHomeError(f"Recently played failed ({status}).")
    return {
        "items": parse_recently_played(_json_object(response)),
        "limit": RECENT_LIMIT,
        "reads": [f"GET /{RECENT_ENDPOINT}?limit={RECENT_LIMIT}"],
    }


def _items(payload):
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return items


def _json_object(response):
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _row(item):
    if not isinstance(item, dict):
        return None
    raw = item.get("track")
    if not isinstance(raw, dict):
        return None
    name = _text(raw.get("name"))
    uri = _text(raw.get("uri"))
    if not name and not uri:
        return None
    album_name, image = _album(raw.get("album"))
    track_id = raw.get("id")
    return {
        "id": track_id if isinstance(track_id, str) else "",
        "uri": uri,
        "name": name,
        "artists": _artists(raw.get("artists")),
        "album": album_name,
        "image": image or None,
        "played_at": _text(item.get("played_at")),
    }


def _artists(artists):
    names = []
    if not isinstance(artists, list):
        return names
    for artist in artists:
        if isinstance(artist, dict):
            name = _text(artist.get("name"))
        elif isinstance(artist, str):
            name = artist.strip()
        else:
            continue
        if name and name not in names:
            names.append(name)
    return names


def _album(album):
    if isinstance(album, dict):
        image = ""
        images = album.get("images") or []
        if isinstance(images, list):
            for candidate in images:
                if isinstance(candidate, dict) and _text(candidate.get("url")):
                    image = _text(candidate.get("url"))
                    break
        return _text(album.get("name")), image
    if isinstance(album, str):
        return album.strip(), ""
    return "", ""
