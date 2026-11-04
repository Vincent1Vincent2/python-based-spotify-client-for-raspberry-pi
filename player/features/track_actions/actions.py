"""Spotify calls for the extra track-menu actions.

Save is one PUT /me/library?uris=spotify:track:{id}.
Adding to a playlist is one POST /playlists/{id}/items.
"""


def save_uri(track_id):
    """Build the spotify:track URI for PUT /me/library?uris=."""
    value = str(track_id or "").strip()
    prefix = "spotify:track:"
    if value.startswith(prefix):
        track_key = value[len(prefix):].strip()
    elif value.startswith("spotify:"):
        raise ValueError("Track ID required")
    else:
        track_key = value
    if not track_key or any(char in track_key for char in "/?#& "):
        raise ValueError("Track ID required")
    return prefix + track_key


def save_track(api, track_id):
    """PUT /me/library?uris=spotify:track:{id} once."""
    uri = save_uri(track_id)
    response = api.put("me/library", params={"uris": uri})
    return {"uri": uri, "response": response}


def add_track_to_playlist(api, playlist_id, uri):
    """POST /playlists/{id}/items exactly once for this track."""
    playlist_id = str(playlist_id or "").strip()
    raw = str(uri or "").strip()
    if not playlist_id:
        raise ValueError("playlist_id is required")
    if not raw:
        raise ValueError("uri is required")
    track_uri = raw if raw.startswith("spotify:") else save_uri(raw)
    return api.add_playlist_items(playlist_id, [track_uri])
