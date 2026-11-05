"""Playback context chip.

Spotify's player payload already includes ``context`` (type and uri).
This module turns that object into the /current-playback/ field and a
short label. It does not request playlist, album, artist, or show names.
"""

CONTEXT_LABELS = {
    'playlist': 'Playlist',
    'album': 'Album',
    'artist': 'Artist',
    'show': 'Show',
}


def context_label(uri):
    """Map a Spotify context uri to Playlist, Album, Artist, Show, or None.

    Accepts ``spotify:playlist``, ``spotify:album``, ``spotify:artist``,
    and ``spotify:show``, with or without a trailing id. ``None`` and
    unknown kinds return None.
    """
    if uri is None or not isinstance(uri, str):
        return None
    parts = [part for part in uri.split(':') if part]
    if len(parts) >= 2 and parts[0] == 'spotify':
        kind = parts[1]
    elif parts:
        kind = parts[0]
    else:
        return None
    return CONTEXT_LABELS.get(kind)


def playback_context(playback):
    """Return ``{type, uri}`` when a player payload has a context, else None."""
    if not isinstance(playback, dict):
        return None
    raw = playback.get('context')
    if not isinstance(raw, dict):
        return None
    context_type = raw.get('type')
    uri = raw.get('uri')
    if not context_type and not uri:
        return None
    return {'type': context_type, 'uri': uri}


def _device_json(device):
    device = device or {}
    return {
        'id': device.get('id'),
        'name': device.get('name'),
        'type': device.get('type'),
        'volume_percent': device.get('volume_percent'),
    }


def build_current_playback(playback):
    """JSON body for /current-playback/ from one Spotify player payload.

    When ``playback.context`` exists, the result includes ``context``
    with type and uri only.
    """
    if not isinstance(playback, dict):
        playback = {}

    item = playback.get('item')
    currently_playing_type = playback.get('currently_playing_type', 'track')
    is_playing = playback.get('is_playing', False)
    device = playback.get('device', {}) or {}
    progress_ms = playback.get('progress_ms', 0)

    if item:
        item_type = item.get('type', currently_playing_type)
        if item_type == 'episode':
            show = item.get('show', {}) or {}
            images = item.get('images', []) or []
            payload = {
                'is_playing': is_playing,
                'track': {
                    'id': item.get('id'),
                    'name': item.get('name', 'Unknown Episode'),
                    'show': show.get('name', 'Unknown Podcast') if show else 'Unknown Podcast',
                    'description': item.get('description', ''),
                    'image': images[0]['url'] if images and len(images) > 0 else None,
                    'duration_ms': item.get('duration_ms', 0),
                    'progress_ms': progress_ms,
                    'type': 'episode',
                },
                'type': 'episode',
                'shuffle_state': playback.get('shuffle_state'),
                'repeat_state': playback.get('repeat_state'),
                'device': _device_json(device),
            }
        else:
            album = item.get('album', {}) or {}
            artists = item.get('artists', []) or []
            album_images = album.get('images', []) or []
            payload = {
                'is_playing': is_playing,
                'track': {
                    'id': item.get('id'),
                    'uri': item.get('uri'),
                    'name': item.get('name', 'Unknown Track'),
                    'artists': [artist.get('name', 'Unknown Artist') for artist in artists],
                    'album': album.get('name', 'Unknown Album'),
                    'album_uri': album.get('uri'),
                    'album_id': album.get('id') or '',
                    'image': album_images[0]['url'] if album_images and len(album_images) > 0 else None,
                    'duration_ms': item.get('duration_ms', 0),
                    'progress_ms': progress_ms,
                    'type': 'track',
                },
                'type': 'track',
                'shuffle_state': playback.get('shuffle_state'),
                'repeat_state': playback.get('repeat_state'),
                'device': _device_json(device),
            }
    else:
        payload = {
            'is_playing': is_playing,
            'track': None,
            'type': None,
            'shuffle_state': playback.get('shuffle_state'),
            'repeat_state': playback.get('repeat_state'),
            'device': _device_json(device) if device else None,
        }

    context = playback_context(playback)
    if context:
        payload['context'] = context
    return payload
