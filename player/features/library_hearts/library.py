"""
Save and unsave tracks and albums in the user's library.

Spotify's per-type routes (GET /me/tracks/contains, PUT /me/tracks,
PUT /me/albums) are gone. One library call covers every URI:

- GET /me/library/contains?uris=
- PUT /me/library?uris=
- DELETE /me/library?uris=

contains() always makes that one GET, even when the list mixes a track
and an album. It does not fetch recommendations, audio features, or
catalog batches.
"""
import re


URI_RE = re.compile(r'^spotify:(track|album):[A-Za-z0-9]+$')
MAX_URIS = 40


class LibraryError(Exception):
    def __init__(self, message, code='library_error'):
        super().__init__(message)
        self.code = code


class LibraryScopeError(LibraryError):
    def __init__(self):
        super().__init__(
            'Reconnect Spotify to save songs and albums.',
            code='needs_scope',
        )


def normalize_uris(value):
    """Comma-separated text or a list, tracks and albums only, order kept."""
    if value is None:
        raw = []
    elif isinstance(value, str):
        raw = value.split(',')
    elif isinstance(value, (list, tuple)):
        raw = []
        for item in value:
            if not isinstance(item, str):
                raise LibraryError('Only Spotify track and album URIs can be saved.')
            raw.extend(item.split(','))
    else:
        raise LibraryError('Only Spotify track and album URIs can be saved.')

    uris = []
    seen = set()
    for item in raw:
        uri = item.strip()
        if not uri:
            continue
        if not URI_RE.match(uri):
            raise LibraryError('Only Spotify track and album URIs can be saved.')
        if uri in seen:
            continue
        seen.add(uri)
        uris.append(uri)

    if not uris:
        raise LibraryError('Give a Spotify track or album URI.')
    if len(uris) > MAX_URIS:
        raise LibraryError('Check at most 40 tracks and albums at once.')
    return uris


def _status(response):
    return getattr(response, 'status_code', 200)


def _spotify_message(response):
    try:
        payload = response.json()
    except Exception:
        return 'Spotify returned %s' % _status(response)
    if isinstance(payload, dict):
        error = payload.get('error')
        if isinstance(error, dict) and error.get('message'):
            return error['message']
        if isinstance(error, str) and error:
            return error
    return 'Spotify returned %s' % _status(response)


def _guard(response):
    status = _status(response)
    if status == 403:
        raise LibraryScopeError()
    if status == 401:
        raise LibraryError('Not authenticated', code='token_expired')
    if status >= 400:
        raise LibraryError(_spotify_message(response))
    return response


def _flags(response, uris):
    try:
        saved = response.json()
    except Exception as exc:
        raise LibraryError('Spotify did not say which items are saved.') from exc
    if not isinstance(saved, list) or len(saved) != len(uris):
        raise LibraryError('Spotify did not say which items are saved.')
    flags = []
    for flag in saved:
        if isinstance(flag, bool):
            flags.append(flag)
        else:
            raise LibraryError('Spotify did not say which items are saved.')
    return flags


def contains(api, uris):
    """One GET /me/library/contains?uris= for every track and album given."""
    normalized = normalize_uris(uris)
    response = _guard(api.library_contains(','.join(normalized)))
    return {'uris': normalized, 'saved': _flags(response, normalized)}


def save(api, uris):
    """PUT /me/library?uris= to save tracks or albums."""
    normalized = normalize_uris(uris)
    _guard(api.save_library_items(','.join(normalized)))
    return {'uris': normalized, 'saved': [True] * len(normalized)}


def remove(api, uris):
    """DELETE /me/library?uris= to remove tracks or albums."""
    normalized = normalize_uris(uris)
    _guard(api.remove_library_items(','.join(normalized)))
    return {'uris': normalized, 'saved': [False] * len(normalized)}
