"""
Pure selection over one page of saved tracks.

GET /me/tracks items look like {"track": {name, artists, album}}.
album.release_date is "YYYY", "YYYY-MM", or "YYYY-MM-DD" when Spotify has it.
Nothing in this module talks to the network.
"""

MATCH_LIMIT = 30


def parse_year_from(value):
    """Return a year, or None when the year filter is left blank."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if not value.isdigit():
            raise ValueError("Year from must be a number.")
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Year from must be a number.")
    if value < 0 or value > 9999:
        raise ValueError("Year from must be a number.")
    return value


def release_year(album):
    """Year from album.release_date, or None when the date is missing."""
    if not isinstance(album, dict):
        return None
    raw = album.get("release_date")
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) < 4 or not text[:4].isdigit():
        return None
    return int(text[:4])


def artist_names(track):
    names = []
    for artist in track.get("artists") or []:
        if isinstance(artist, str):
            if artist:
                names.append(artist)
        elif isinstance(artist, dict):
            name = artist.get("name")
            if name:
                names.append(str(name))
    return names


def _track_of(item):
    if not isinstance(item, dict):
        return None
    nested = item.get("track")
    if isinstance(nested, dict):
        return nested
    if any(key in item for key in ("uri", "name", "album", "artists")):
        return item
    return None


def _contains(text, needle):
    if not needle:
        return True
    return needle in (text or "").lower()


def filter_saved_tracks(items, artist="", title="", year_from=None):
    """
    Keep saved songs whose artist name and title contain the given text.

    year_from, when set, keeps songs whose album.release_date year is that
    year or later. Songs with no release date are left out only when a year
    is requested. At most 30 songs, in the order they were saved.
    """
    artist_q = (artist or "").strip().lower()
    title_q = (title or "").strip().lower()
    if year_from is not None:
        year_from = int(year_from)

    matches = []
    for item in items or []:
        track = _track_of(item)
        if not track or track.get("is_local"):
            continue
        uri = track.get("uri")
        if not isinstance(uri, str) or not uri:
            continue
        if not _contains(track.get("name") or "", title_q):
            continue
        if artist_q and not any(_contains(name, artist_q) for name in artist_names(track)):
            continue
        if year_from is not None:
            album = track.get("album")
            year = release_year(album if isinstance(album, dict) else None)
            if year is None or year < year_from:
                continue
        matches.append(track)
        if len(matches) >= MATCH_LIMIT:
            break
    return matches
