"""
Smart mixes.

One Spotify read, GET /me/tracks?limit=50, then local filters. A private
playlist named Mix 01, Mix 02, ... is created only when at least one saved
song matches. The number lives in the Django session for that account key,
not in a model. Playback is the new playlist. Recommendations are not used.
"""
import logging

from .filter import artist_names, filter_saved_tracks, release_year

logger = logging.getLogger(__name__)

READ_LIMIT = 50
READ_LABEL = "GET /me/tracks?limit=50"
SESSION_COUNTER_PREFIX = "smart_mix_counter:"


class SmartMixError(Exception):
    def __init__(self, message, code="smart_mix_error"):
        super().__init__(message)
        self.code = code


class SmartMixScopeError(SmartMixError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify so Mix can read saved songs and save a private playlist.",
            code="needs_scope",
        )


def session_counter_key(account_key):
    return f"{SESSION_COUNTER_PREFIX}{account_key}"


def mix_title(number):
    return f"Mix {int(number):02d}"


def next_mix_number(session, account_key):
    """Next Mix number for this account, stored on the Django session."""
    account_key = str(account_key or "").strip()
    if not account_key:
        raise SmartMixError("No Spotify account is active.")
    key = session_counter_key(account_key)
    try:
        current = int(session.get(key) or 0)
    except (TypeError, ValueError):
        current = 0
    number = current + 1
    session[key] = number
    return number


def _error_detail(response):
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict):
        return error.get("message") or ""
    if isinstance(error, str):
        return error
    return ""


def _payload(response, action):
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise SmartMixScopeError()
    if status >= 400:
        detail = _error_detail(response)
        message = f"{action} failed ({status})"
        if detail:
            message = f"{message}: {detail}"
        raise SmartMixError(message)
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _description(artist, title, year_from, count):
    filters = []
    artist = (artist or "").strip()
    title = (title or "").strip()
    if artist:
        filters.append(f'artist contains "{artist}"')
    if title:
        filters.append(f'title contains "{title}"')
    if year_from is not None:
        filters.append(f"year from {year_from}")
    detail = ", ".join(filters) if filters else "saved songs"
    return f"Smart mix of {count} saved songs ({detail})."[:300]


def _public_track(track):
    album = track.get("album")
    if isinstance(album, dict):
        album_name = album.get("name") or ""
        year = release_year(album)
    else:
        album_name = album or ""
        year = None
    return {
        "id": track.get("id"),
        "uri": track.get("uri"),
        "name": track.get("name") or "",
        "artists": artist_names(track),
        "album": album_name,
        "year": year,
    }


def _empty(message):
    return {
        "created": False,
        "name": "",
        "playlist_id": "",
        "count": 0,
        "tracks": [],
        "reads": [READ_LABEL],
        "message": message,
    }


def build_smart_mix(api, session, account_key, artist="", title="", year_from=None, device_id=None):
    """
    Read one page of saved songs, filter locally, save a private playlist,
    and play it. An empty match list does not create a playlist.
    """
    response = api.get_user_saved_tracks(limit=READ_LIMIT)
    data = _payload(response, "Read saved songs")
    matches = filter_saved_tracks(
        data.get("items") or [],
        artist=artist,
        title=title,
        year_from=year_from,
    )
    if not matches:
        return _empty("No saved songs matched those filters.")

    if not device_id:
        raise SmartMixError("No device selected", code="no_device")

    number = next_mix_number(session, account_key)
    name = mix_title(number)
    created = _payload(
        api.create_playlist(
            name,
            description=_description(artist, title, year_from, len(matches)),
            public=False,
        ),
        "Create playlist",
    )
    playlist_id = created.get("id")
    if not playlist_id:
        raise SmartMixError("Spotify did not return a playlist id.")

    uris = [track["uri"] for track in matches if track.get("uri")]
    _payload(api.add_playlist_items(playlist_id, uris), "Add songs")

    play = api.start_playback(
        device_id=device_id,
        context_uri=f"spotify:playlist:{playlist_id}",
    )
    if getattr(play, "status_code", 200) >= 400:
        message = f"{name} is saved. Playback did not start on this device."
        logger.warning(
            "smart mix: start_playback status %s",
            getattr(play, "status_code", None),
        )
    else:
        message = f"Playing {name}."

    return {
        "created": True,
        "name": name,
        "playlist_id": playlist_id,
        "count": len(matches),
        "tracks": [_public_track(track) for track in matches],
        "reads": [READ_LABEL],
        "message": message,
    }
