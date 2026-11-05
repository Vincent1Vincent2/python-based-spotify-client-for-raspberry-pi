"""
Artists the user follows.

One Spotify read: GET /me/following?type=artist&limit=50.
The list is artists.items. Each row is a name and an image.
The next cursor is not followed. Related artists and top tracks are
not read. A 403 means the token is missing user-follow-read.
"""
from urllib.parse import quote

ENDPOINT = "me/following"
LIMIT = 50
ARTIST_TYPE = "artist"
SCOPE = "user-follow-read"
LOGIN_PATH = "/login/?auth=1"
ARTIST_PAGE = "/features/artist-pages/"


class FollowedArtistsError(Exception):
    def __init__(self, message, code="followed_artists_error", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class NeedsScope(FollowedArtistsError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify to show artists you follow.",
            code="needs_scope",
            status=403,
        )
        self.login = LOGIN_PATH


def artist_page_url(artist_id):
    return f"{ARTIST_PAGE}?id={quote(artist_id, safe='')}"


def _image(artist):
    images = artist.get("images") or []
    if not isinstance(images, list):
        return ""
    for image in images:
        if not isinstance(image, dict):
            continue
        url = image.get("url") or ""
        if url.startswith("https://") or url.startswith("http://"):
            return url
    return ""


def row_from_item(item):
    """One followed artist: id, name, and image."""
    if not isinstance(item, dict) or not item:
        return None
    artist_id = item.get("id") or ""
    if not isinstance(artist_id, str):
        artist_id = str(artist_id)
    artist_id = artist_id.strip()
    if not artist_id:
        return None
    name = item.get("name") or ""
    if not isinstance(name, str):
        name = str(name)
    return {
        "id": artist_id,
        "name": name.strip(),
        "image": _image(item),
        "url": artist_page_url(artist_id),
    }


def artists_from_payload(payload):
    """Read artists.items. A missing or empty list is an empty list."""
    artists = payload.get("artists") if isinstance(payload, dict) else None
    items = artists.get("items") if isinstance(artists, dict) else None
    if not isinstance(items, list):
        return []
    rows = []
    for item in items:
        row = row_from_item(item)
        if row:
            rows.append(row)
    return rows


def load_followed_artists(api):
    """The only read this feature makes."""
    response = api.get(ENDPOINT, params={"type": ARTIST_TYPE, "limit": LIMIT})
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise NeedsScope()
    if status >= 400:
        raise FollowedArtistsError(f"Spotify API error: {status}", status=502)
    if status == 204:
        payload = {}
    else:
        payload = response.json() or {}
    return artists_from_payload(payload)
