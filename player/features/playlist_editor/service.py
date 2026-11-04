"""
Edit private playlists through the Development Mode Web API.

Creates use POST /me/playlists with public false. Name and description
use PUT /playlists/{id}. Removing a playlist is DELETE
DELETE /me/library with the playlist URI, which only takes it out of the library.
Items use /playlists/{id}/items, 50 at a time. Reordering sends
range_start, insert_before, and range_length, never a replacement list.
"""

import re

PAGE_SIZE = 50

_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9]+$")
_TRACK_URI = re.compile(r"^spotify:track:([A-Za-z0-9]+)$")
_TRACK_URL = re.compile(
    r"(?:https?://)?open\.spotify\.com/track/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_BARE_TRACK_ID = re.compile(r"^[A-Za-z0-9]{22}$")


class PlaylistEditorError(Exception):
    def __init__(self, message, status=400, code="playlist_editor"):
        super().__init__(message)
        self.status = status
        self.code = code


def insert_before_index(start, destination):
    """
    insert_before is an index in the playlist before the move.

    Moving the first of 10 items to the last index uses insert_before 10.
    Moving the last of those 10 items to the start uses insert_before 0.
    Moving one slot down therefore uses insert_before = start + 2.
    """
    if start < 0 or destination < 0:
        raise PlaylistEditorError("That track position is not in the playlist.")
    if start == destination:
        raise PlaylistEditorError("That track is already there.")
    if start < destination:
        return destination + 1
    return destination


def reorder_move(index, direction, total):
    """One track, one slot. Returns range_start, insert_before, range_length."""
    if isinstance(index, bool) or not isinstance(index, int):
        raise PlaylistEditorError("Choose a track to move.")
    if not isinstance(total, int) or isinstance(total, bool) or total < 1:
        raise PlaylistEditorError("This playlist has no tracks to move.")
    if index < 0 or index >= total:
        raise PlaylistEditorError("That track is no longer at this position.")
    if direction == "up":
        if index == 0:
            raise PlaylistEditorError("That track is already first.")
        destination = index - 1
    elif direction == "down":
        if index >= total - 1:
            raise PlaylistEditorError("That track is already last.")
        destination = index + 1
    else:
        raise PlaylistEditorError("Move the track up or down.")
    return index, insert_before_index(index, destination), 1


def clean_playlist_id(value):
    text = (value or "").strip()
    if not _PLAYLIST_ID.match(text):
        raise PlaylistEditorError("Enter a playlist id.")
    return text


def clean_name(name):
    text = " ".join(str(name or "").split())
    if not text:
        raise PlaylistEditorError("Enter a playlist name.")
    if len(text) > 100:
        raise PlaylistEditorError("Playlist names can be at most 100 characters.")
    return text


def clean_description(description):
    if description is None:
        return ""
    text = str(description).strip()
    if len(text) > 300:
        raise PlaylistEditorError("Descriptions can be at most 300 characters.")
    return text


def normalize_track_uri(value):
    text = (value or "").strip()
    if text.lower().startswith("spotify:episode:"):
        raise PlaylistEditorError("Add a track URI. Episode URIs are not accepted here.")
    match = _TRACK_URI.match(text)
    if match:
        return f"spotify:track:{match.group(1)}"
    match = _TRACK_URL.search(text)
    if match:
        return f"spotify:track:{match.group(1)}"
    if _BARE_TRACK_ID.match(text):
        return f"spotify:track:{text}"
    raise PlaylistEditorError(
        "Enter a Spotify track URI, like spotify:track:11dFghVXANMlKmJXsNCbNl."
    )


def parse_offset(value):
    if value in (None, "", "0"):
        return 0
    if value == "end":
        return "end"
    if isinstance(value, bool):
        raise PlaylistEditorError("Offset must be a number.")
    try:
        offset = int(value)
    except (TypeError, ValueError):
        raise PlaylistEditorError("Offset must be a number.")
    if offset < 0:
        raise PlaylistEditorError("Offset cannot be negative.")
    return offset


def json_object(response):
    try:
        payload = response.json()
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def raise_for_spotify(response):
    status = getattr(response, "status_code", 500)
    if status < 400:
        return
    message = f"Spotify returned {status}."
    error = json_object(response).get("error")
    if isinstance(error, dict) and error.get("message"):
        message = error["message"]
    elif isinstance(error, str) and error:
        message = error
    if status == 401:
        raise PlaylistEditorError(message, status=401, code="spotify_unauthorized")
    if status == 403:
        raise PlaylistEditorError(message, status=403, code="spotify_forbidden")
    raise PlaylistEditorError(message, status=400, code="spotify_error")


def paging_total(playlist):
    """Playlist length. February 2026 renamed tracks to items."""
    if not isinstance(playlist, dict):
        return None
    for key in ("items", "tracks"):
        value = playlist.get(key)
        if isinstance(value, dict) and "total" in value:
            try:
                return int(value.get("total") or 0)
            except (TypeError, ValueError):
                return 0
    return None


def _owner_name(playlist):
    owner = playlist.get("owner") or {}
    if not isinstance(owner, dict):
        return ""
    return owner.get("display_name") or owner.get("id") or ""


def _image_url(images):
    if not isinstance(images, list):
        return None
    for image in reversed(images):
        if isinstance(image, dict) and image.get("url"):
            return image["url"]
    return None


def _summary(playlist):
    return {
        "id": playlist.get("id") or "",
        "name": playlist.get("name") or "",
        "description": playlist.get("description") or "",
        "public": playlist.get("public"),
        "private": playlist.get("public") is False,
        "tracks_count": paging_total(playlist) or 0,
        "owner": _owner_name(playlist),
        "image": _image_url(playlist.get("images")),
        "snapshot_id": playlist.get("snapshot_id") or "",
    }


def _media(entry):
    if not isinstance(entry, dict):
        return None
    for key in ("item", "track"):
        value = entry.get(key)
        if isinstance(value, dict):
            return value
    return None


def _artists(media):
    names = []
    for artist in media.get("artists") or []:
        if isinstance(artist, dict) and artist.get("name"):
            names.append(artist["name"])
    if not names:
        show = media.get("show")
        if isinstance(show, dict) and show.get("name"):
            names.append(show["name"])
    return names


def _row(entry, position):
    media = _media(entry)
    if not media:
        return {
            "position": position,
            "uri": "",
            "id": "",
            "name": "Unavailable",
            "artists": [],
            "album": "",
            "image": None,
            "duration_ms": 0,
            "available": False,
        }
    album = media.get("album") if isinstance(media.get("album"), dict) else {}
    uri = media.get("uri") or ""
    local = bool(entry.get("is_local") or media.get("is_local"))
    return {
        "position": position,
        "uri": uri,
        "id": media.get("id") or "",
        "name": media.get("name") or "Unavailable",
        "artists": _artists(media),
        "album": album.get("name") or "",
        "image": _image_url(album.get("images")) or _image_url(media.get("images")),
        "duration_ms": media.get("duration_ms") or 0,
        "available": bool(uri.startswith("spotify:track:")) and not local,
    }


def fetch_playlist(api, playlist_id):
    response = api.get_playlist(playlist_id)
    raise_for_spotify(response)
    payload = json_object(response)
    if not payload.get("id"):
        raise PlaylistEditorError("Spotify did not return that playlist.")
    return payload


def list_playlists(api, offset=0):
    offset = parse_offset(offset)
    if offset == "end":
        offset = 0
    response = api.get_user_playlists(limit=PAGE_SIZE, offset=offset)
    raise_for_spotify(response)
    payload = json_object(response)
    playlists = []
    for playlist in payload.get("items") or []:
        if isinstance(playlist, dict) and playlist.get("id"):
            playlists.append(_summary(playlist))
    return {
        "playlists": playlists,
        "offset": offset,
        "limit": PAGE_SIZE,
        "has_more": bool(payload.get("next")),
        "total": payload.get("total") or 0,
    }


def _clamp_offset(offset, total):
    if offset == "end":
        if total <= 0:
            return 0
        return ((total - 1) // PAGE_SIZE) * PAGE_SIZE
    if total and offset >= total:
        return ((total - 1) // PAGE_SIZE) * PAGE_SIZE
    return offset


def playlist_detail(api, playlist_id, offset=0):
    playlist_id = clean_playlist_id(playlist_id)
    offset = parse_offset(offset)
    playlist = fetch_playlist(api, playlist_id)
    total = paging_total(playlist)
    if total is None:
        total = 0
    offset = _clamp_offset(offset, total)
    response = api.get_playlist_items(playlist_id, limit=PAGE_SIZE, offset=offset)
    raise_for_spotify(response)
    payload = json_object(response)
    if payload.get("total") is not None:
        try:
            total = int(payload.get("total") or 0)
        except (TypeError, ValueError):
            pass
    rows = []
    for index, entry in enumerate(payload.get("items") or []):
        rows.append(_row(entry, offset + index))
    summary = _summary(playlist)
    summary.update({
        "tracks_count": total,
        "offset": offset,
        "limit": PAGE_SIZE,
        "has_more": bool(payload.get("next")),
        "tracks": rows,
    })
    return summary


def create_private_playlist(api, name, description=""):
    name = clean_name(name)
    description = clean_description(description)
    response = api.create_playlist(name, description=description, public=False)
    raise_for_spotify(response)
    payload = json_object(response)
    playlist_id = payload.get("id")
    if not playlist_id:
        raise PlaylistEditorError("Spotify did not return the new playlist.")
    return {
        "id": playlist_id,
        "name": payload.get("name") or name,
        "description": payload.get("description") if payload.get("description") is not None else description,
        "public": False,
        "private": True,
        "snapshot_id": payload.get("snapshot_id") or "",
    }


def update_playlist(api, playlist_id, name=None, description=None, fields=()):
    playlist_id = clean_playlist_id(playlist_id)
    fields = set(fields or ())
    if not fields:
        raise PlaylistEditorError("Change the name, the description, or both.")
    new_name = clean_name(name) if "name" in fields else None
    new_description = clean_description(description) if "description" in fields else None
    response = api.update_playlist_details(
        playlist_id,
        name=new_name,
        description=new_description,
    )
    raise_for_spotify(response)
    payload = json_object(response)
    return {
        "id": playlist_id,
        "name": payload.get("name") if payload.get("name") is not None else new_name,
        "description": (
            payload.get("description")
            if payload.get("description") is not None
            else (new_description if new_description is not None else "")
        ),
        "snapshot_id": payload.get("snapshot_id") or "",
    }


def remove_from_library(api, playlist_id):
    playlist_id = clean_playlist_id(playlist_id)
    playlist = fetch_playlist(api, playlist_id)
    if playlist.get("public") is not False:
        raise PlaylistEditorError(
            "This playlist is not private, so it was not removed.",
            code="not_private",
        )
    response = api.remove_playlist_from_library(playlist_id)
    raise_for_spotify(response)
    return {
        "removed": True,
        "id": playlist_id,
        "name": playlist.get("name") or "",
    }


def add_track(api, playlist_id, uri):
    playlist_id = clean_playlist_id(playlist_id)
    uri = normalize_track_uri(uri)
    response = api.add_playlist_items(playlist_id, [uri])
    raise_for_spotify(response)
    payload = json_object(response)
    return {
        "id": playlist_id,
        "uri": uri,
        "snapshot_id": payload.get("snapshot_id") or "",
    }


def _page_for_index(api, playlist_id, index):
    page_offset = (index // PAGE_SIZE) * PAGE_SIZE
    response = api.get_playlist_items(playlist_id, limit=PAGE_SIZE, offset=page_offset)
    raise_for_spotify(response)
    payload = json_object(response)
    items = payload.get("items") or []
    local = index - page_offset
    if local < 0 or local >= len(items):
        raise PlaylistEditorError("That track is no longer at this position.")
    return items[local]


def _require_same_uri(entry, uri):
    media = _media(entry) or {}
    found = media.get("uri") or ""
    if found != uri:
        raise PlaylistEditorError("That track moved. Reload the playlist and try again.")


def remove_track(api, playlist_id, uri, index):
    playlist_id = clean_playlist_id(playlist_id)
    uri = normalize_track_uri(uri)
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise PlaylistEditorError("Choose a track to remove.")
    playlist = fetch_playlist(api, playlist_id)
    entry = _page_for_index(api, playlist_id, index)
    _require_same_uri(entry, uri)
    response = api.remove_playlist_items(
        playlist_id,
        [uri],
        snapshot_id=playlist.get("snapshot_id") or None,
        positions=[index],
    )
    raise_for_spotify(response)
    payload = json_object(response)
    return {
        "id": playlist_id,
        "uri": uri,
        "index": index,
        "snapshot_id": payload.get("snapshot_id") or playlist.get("snapshot_id") or "",
    }


def move_track(api, playlist_id, index, direction, uri=None):
    playlist_id = clean_playlist_id(playlist_id)
    if isinstance(index, bool) or not isinstance(index, int):
        raise PlaylistEditorError("Choose a track to move.")
    playlist = fetch_playlist(api, playlist_id)
    total = paging_total(playlist)
    if total is None:
        raise PlaylistEditorError("Spotify did not say how many tracks are in this playlist.")
    range_start, insert_before, range_length = reorder_move(index, direction, total)
    if uri:
        uri = normalize_track_uri(uri)
        _require_same_uri(_page_for_index(api, playlist_id, index), uri)
    response = api.reorder_playlist_items(
        playlist_id,
        range_start=range_start,
        insert_before=insert_before,
        range_length=range_length,
        snapshot_id=playlist.get("snapshot_id") or None,
    )
    raise_for_spotify(response)
    payload = json_object(response)
    return {
        "id": playlist_id,
        "index": index,
        "direction": direction,
        "range_start": range_start,
        "insert_before": insert_before,
        "range_length": range_length,
        "snapshot_id": payload.get("snapshot_id") or playlist.get("snapshot_id") or "",
    }
