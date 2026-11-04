"""
Song radio.

From one track, at most two Spotify reads fill a private playlist:

1. GET /albums/{album_id}/tracks?limit=50 when the seed includes an album
   id, otherwise GET /me/tracks?limit=50.
2. One search, limit 10. Development Mode rejects a higher search limit.
   The query is build_query from player.feel for that seed.

order_for_radio chains the pile from the seed. The writes are one
POST /me/playlists (public false, name "{track name} Radio" at 80
characters), one POST of the track URIs, and start_playback on that
playlist. Recommendations and audio features are not used.
"""
import logging

from player.feel import (
    build_query,
    order_for_radio,
    tracks_from_paging,
    tracks_from_search,
)

logger = logging.getLogger(__name__)

PLAYLIST_SIZE = 30
READ_LIMIT = 50
SEARCH_LIMIT = 10
NAME_LIMIT = 80
_NAME_SUFFIX = " Radio"


class SongRadioError(Exception):
    def __init__(self, message, code="song_radio_error"):
        super().__init__(message)
        self.code = code


class SongRadioScopeError(SongRadioError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify so song radio can save a private playlist.",
            code="needs_scope",
        )


def song_radio_title(track_name):
    """'{track name} Radio', never longer than 80 characters."""
    base = " ".join(str(track_name or "").split())
    if not base:
        raise SongRadioError("That song has no name.")
    title = f"{base}{_NAME_SUFFIX}"
    if len(title) <= NAME_LIMIT:
        return title
    trimmed = base[: NAME_LIMIT - len(_NAME_SUFFIX)].rstrip()
    if not trimmed:
        return title[:NAME_LIMIT]
    return f"{trimmed}{_NAME_SUFFIX}"


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _album_id(raw):
    if not isinstance(raw, dict):
        return ""
    value = raw.get("album_id")
    album = raw.get("album")
    if not value and isinstance(album, dict):
        value = album.get("id") or ""
        if not value:
            album_uri = _text(album.get("uri"))
            if album_uri.startswith("spotify:album:"):
                value = album_uri.split(":")[-1]
    if not isinstance(value, str):
        value = str(value).strip() if value else ""
    else:
        value = value.strip()
    if value.startswith("spotify:album:"):
        value = value.split(":")[-1]
    if value.lower() in {"", "none", "null", "undefined"}:
        return ""
    if any(char in value for char in "/?#& "):
        return ""
    return value


def _artists(raw):
    values = raw.get("artists") if isinstance(raw, dict) else None
    if isinstance(values, str):
        values = [part.strip() for part in values.split(",")]
    artists = []
    for artist in values or []:
        if isinstance(artist, dict):
            name = _text(artist.get("name"))
        elif isinstance(artist, str):
            name = artist.strip()
        else:
            name = ""
        if name and name not in artists:
            artists.append(name)
    return artists


def _album_name(raw):
    album = raw.get("album") if isinstance(raw, dict) else None
    if isinstance(album, dict):
        return _text(album.get("name"))
    if isinstance(album, str):
        return album.strip()
    return ""


def normalize_seed(raw):
    """Name, artists, and a spotify:track URI. Album id is optional."""
    if not isinstance(raw, dict):
        raise SongRadioError("Choose a song first.")
    uri = _text(raw.get("uri"))
    if not uri.startswith("spotify:track:"):
        raise SongRadioError("That song has no Spotify track URI.")
    name = " ".join(_text(raw.get("name")).split())
    if not name:
        raise SongRadioError("That song has no name.")
    track = {
        "id": uri.split(":")[-1],
        "uri": uri,
        "name": name,
        "artists": _artists(raw),
        "album": _album_name(raw),
    }
    return track, _album_id(raw)


def _payload(response, action):
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise SongRadioScopeError()
    if status >= 400:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    detail = error.get("message") or ""
                elif isinstance(error, str):
                    detail = error
        except Exception:
            detail = ""
        message = f"{action} failed ({status})"
        if detail:
            message = f"{message}: {detail}"
        raise SongRadioError(message)
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _read_catalog(api, album_id):
    if album_id:
        response = api.get_album_tracks(album_id, limit=READ_LIMIT, offset=0)
        label = f"GET /albums/{album_id}/tracks?limit={READ_LIMIT}"
        action = "Read album"
    else:
        response = api.get_user_saved_tracks(limit=READ_LIMIT, offset=0)
        label = f"GET /me/tracks?limit={READ_LIMIT}"
        action = "Read saved songs"
    tracks = tracks_from_paging(_payload(response, action))
    return tracks, label


def _search_once(api, seed):
    """One search, and only when build_query has something to say."""
    query = build_query([], seed)
    if not query:
        return [], "", None
    response = api.search(q=query, type="track", limit=SEARCH_LIMIT, offset=0)
    tracks = tracks_from_search(_payload(response, "Search"))
    return tracks, query, f"GET /search?limit={SEARCH_LIMIT}"


def _public_track(track):
    return {
        "id": track.get("id"),
        "uri": track.get("uri"),
        "name": track.get("name") or "",
        "artists": list(track.get("artists") or []),
        "album": track.get("album") or "",
    }


def start_song_radio(api, seed, device_id):
    """
    Read at most twice, create one private playlist, add its songs in
    one request, and play that playlist.
    """
    seed_track, album_id = normalize_seed(seed)
    catalog, catalog_label = _read_catalog(api, album_id)
    found, query, search_label = _search_once(api, seed_track)
    reads = [catalog_label]
    if search_label:
        reads.append(search_label)

    ordered = order_for_radio([seed_track] + catalog + found, [], seed_track)
    batch = ordered[:PLAYLIST_SIZE]
    if not batch:
        raise SongRadioError("No songs came back for this radio.")

    name = song_radio_title(seed_track["name"])
    description = f"Song radio from {seed_track['name']}."[:300]
    created = _payload(
        api.create_playlist(name, description=description, public=False),
        "Create playlist",
    )
    playlist_id = created.get("id")
    if not playlist_id:
        raise SongRadioError("Spotify did not return a playlist id.")

    uris = [track["uri"] for track in batch if track.get("uri")]
    _payload(api.add_playlist_items(playlist_id, uris), "Add songs")

    play_message = ""
    play = api.start_playback(
        device_id=device_id,
        context_uri=f"spotify:playlist:{playlist_id}",
    )
    if getattr(play, "status_code", 200) >= 400:
        play_message = "The playlist is saved. Playback did not start on this device."
        logger.warning("song radio: start_playback status %s", getattr(play, "status_code", None))

    message = play_message or f"Playing {name}."
    if len(batch) < PLAYLIST_SIZE:
        short = f"{len(batch)} songs were available."
        message = f"{message} {short}".strip()
    return {
        "name": name,
        "playlist_id": playlist_id,
        "tracks": [_public_track(track) for track in batch],
        "reads": reads,
        "query": query,
        "count": len(batch),
        "message": message,
    }
