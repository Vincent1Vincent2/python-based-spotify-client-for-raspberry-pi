"""
Recently played tracks.

One Spotify read: GET /me/player/recently-played?limit=50.
Playing a row calls start_playback with uris=[that uri].
A 403 on the read means the token is missing user-read-recently-played.
"""

ENDPOINT = "me/player/recently-played"
LIMIT = 50
SCOPE = "user-read-recently-played"
LOGIN_PATH = "/login/?auth=1"


class RecentlyPlayedError(Exception):
    def __init__(self, message, code="recently_played_error", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class NeedsScope(RecentlyPlayedError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify to show recently played tracks.",
            code="needs_scope",
            status=403,
        )
        self.login = LOGIN_PATH


def _artist_names(track):
    names = []
    for artist in track.get("artists") or []:
        if isinstance(artist, str):
            name = artist.strip()
        elif isinstance(artist, dict):
            name = (artist.get("name") or "").strip()
        else:
            name = ""
        if name:
            names.append(name)
    return names


def _image(track):
    album = track.get("album") if isinstance(track.get("album"), dict) else {}
    images = album.get("images") or []
    if not images or not isinstance(images[0], dict):
        return ""
    url = images[0].get("url") or ""
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return ""


def row_from_item(item):
    """One history row: track title, artist names, played_at, and its uri."""
    if not isinstance(item, dict):
        return None
    track = item.get("track")
    if not isinstance(track, dict) or not track:
        return None
    uri = (track.get("uri") or "").strip()
    if not uri:
        return None
    played_at = item.get("played_at") or ""
    if not isinstance(played_at, str):
        played_at = str(played_at)
    return {
        "track": track.get("name") or "",
        "artists": _artist_names(track),
        "played_at": played_at,
        "uri": uri,
        "image": _image(track),
    }


def rows_from_payload(payload):
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    rows = []
    for item in items:
        row = row_from_item(item)
        if row:
            rows.append(row)
    return rows


def load_recently_played(api):
    """The only read this feature makes."""
    response = api.get(ENDPOINT, params={"limit": LIMIT})
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise NeedsScope()
    if status >= 400:
        raise RecentlyPlayedError(f"Spotify API error: {status}", status=502)
    payload = {} if status == 204 else (response.json() or {})
    return rows_from_payload(payload)


def play_recent(api, uri, device_id=None):
    """Play that row and nothing else around it."""
    uri = (uri or "").strip()
    if not uri.startswith("spotify:"):
        raise RecentlyPlayedError("A Spotify URI is required.")
    response = api.start_playback(device_id=device_id or None, uris=[uri])
    status = getattr(response, "status_code", 204)
    if status >= 400:
        raise RecentlyPlayedError(
            f"Spotify API error: {status}",
            code="playback_error",
            status=502,
        )
    return {"status": "playing", "uri": uri}
