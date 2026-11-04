"""
Saved podcasts.

Each read is one Spotify page: the user's shows, one show, or that
show's episodes. Saving and removing send one show URI to the library.
Playing an episode passes that episode URI to start_playback.
"""
import re


PAGE_LIMIT = 50

_SPOTIFY_ID = re.compile(r'^[A-Za-z0-9]{1,64}$')
_SHOW_REF = re.compile(
    r'(?:spotify:show:|(?:https?://)?open\.spotify\.com/'
    r'(?:intl-[A-Za-z0-9-]+/)?show/)([A-Za-z0-9]{1,64})'
)


class PodcastShelfError(Exception):
    def __init__(self, message, code='podcast_error', status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class PodcastScopeError(PodcastShelfError):
    def __init__(self):
        super().__init__(
            'Reconnect Spotify to use your shows.',
            code='needs_scope',
            status=403,
        )


def page_offset(value):
    try:
        offset = int(value)
    except (TypeError, ValueError):
        raise PodcastShelfError('Offset must be a whole number.')
    if offset < 0:
        raise PodcastShelfError('Offset must be a whole number.')
    return offset


def require_spotify_id(value):
    text = str(value or '').strip()
    if not _SPOTIFY_ID.fullmatch(text):
        raise PodcastShelfError('That Spotify id is not valid.')
    return text


def parse_show_reference(value):
    """One show id, a spotify:show URI, or an open.spotify.com show link."""
    text = str(value or '').strip()
    if not text:
        raise PodcastShelfError('Paste a Spotify show link.')
    lowered = text.lower()
    if ',' in text or 'ids=' in lowered:
        raise PodcastShelfError('Save one show at a time.')
    match = _SHOW_REF.search(text)
    if match:
        return match.group(1)
    return require_spotify_id(text)


def list_saved_shows(api, offset=0):
    payload = _object(
        api.get_saved_shows(limit=PAGE_LIMIT, offset=offset),
        'Loading shows',
    )
    shows = []
    for item in _items(payload):
        show = item.get('show') if isinstance(item, dict) else None
        if isinstance(show, dict) and isinstance(show.get('id'), str) and show.get('id'):
            shows.append(public_show(show))
    return {
        'shows': shows,
        'has_more': _has_more(payload),
        'offset': offset,
        'limit': PAGE_LIMIT,
        'total': _total(payload),
    }


def show_detail(api, show_id, offset=0):
    show_id = require_spotify_id(show_id)
    show_payload = _object(api.get_show(show_id), 'Loading show')
    episodes_payload = _object(
        api.get_show_episodes(show_id, limit=PAGE_LIMIT, offset=offset),
        'Loading episodes',
    )
    episodes = []
    for episode in _items(episodes_payload):
        if isinstance(episode, dict) and isinstance(episode.get('id'), str) and episode.get('id'):
            episodes.append(public_episode(episode))
    return {
        'show': public_show(show_payload),
        'episodes': episodes,
        'has_more': _has_more(episodes_payload),
        'offset': offset,
        'limit': PAGE_LIMIT,
        'total': _total(episodes_payload),
    }


def save_show(api, reference):
    show_id = parse_show_reference(reference)
    _object(api.save_show(show_id), 'Saving show')
    return {
        'status': 'saved',
        'id': show_id,
        'uri': f'spotify:show:{show_id}',
    }


def remove_show(api, show_id):
    show_id = require_spotify_id(show_id)
    _object(api.remove_show(show_id), 'Removing show')
    return {
        'status': 'removed',
        'id': show_id,
        'uri': f'spotify:show:{show_id}',
    }


def play_episode(api, episode_id, device_id=None):
    episode_id = require_spotify_id(episode_id)
    uri = f'spotify:episode:{episode_id}'
    kwargs = {'uris': [uri]}
    if device_id:
        kwargs['device_id'] = device_id
    _object(api.start_playback(**kwargs), 'Playing episode')
    return {
        'status': 'playing',
        'episode_id': episode_id,
        'uri': uri,
    }


def public_show(show):
    if not isinstance(show, dict):
        show = {}
    show_id = show.get('id') if isinstance(show.get('id'), str) else ''
    return {
        'id': show_id,
        'name': _text(show.get('name')),
        'publisher': _text(show.get('publisher')),
        'description': _text(show.get('description')),
        'image': _image(show),
        'total_episodes': _nonnegative(show.get('total_episodes')),
        'uri': f'spotify:show:{show_id}' if show_id else '',
        'explicit': bool(show.get('explicit')),
    }


def public_episode(episode):
    if not isinstance(episode, dict):
        episode = {}
    episode_id = episode.get('id') if isinstance(episode.get('id'), str) else ''
    return {
        'id': episode_id,
        'name': _text(episode.get('name')),
        'description': _text(episode.get('description')),
        'duration_ms': _nonnegative(episode.get('duration_ms')),
        'release_date': _text(episode.get('release_date')),
        'image': _image(episode),
        'uri': f'spotify:episode:{episode_id}' if episode_id else '',
        'explicit': bool(episode.get('explicit')),
        'resume_position_ms': _resume_ms(episode),
    }


def _object(response, action):
    status = getattr(response, 'status_code', 200)
    if status == 401:
        raise PodcastShelfError(
            'Not authenticated',
            code='token_expired',
            status=401,
        )
    if status == 403:
        raise PodcastScopeError()
    if status >= 400:
        raise PodcastShelfError(_failure_text(response, action, status))
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _failure_text(response, action, status):
    detail = ''
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        error = body.get('error')
        if isinstance(error, dict) and isinstance(error.get('message'), str):
            detail = error.get('message')
        elif isinstance(error, str):
            detail = error
    text = f'{action} failed ({status})'
    if detail:
        text = f'{text}: {detail}'
    return text


def _items(payload):
    if not isinstance(payload, dict):
        return []
    items = payload.get('items')
    if not isinstance(items, list):
        return []
    return items


def _has_more(payload):
    return bool(isinstance(payload, dict) and payload.get('next'))


def _total(payload):
    if not isinstance(payload, dict):
        return 0
    return _nonnegative(payload.get('total'))


def _text(value):
    return value if isinstance(value, str) else ''


def _nonnegative(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _image(item):
    images = item.get('images') if isinstance(item, dict) else None
    if not isinstance(images, list) or not images or not isinstance(images[0], dict):
        return None
    url = images[0].get('url')
    if isinstance(url, str) and (url.startswith('https://') or url.startswith('http://')):
        return url
    return None


def _resume_ms(episode):
    resume = episode.get('resume_point')
    if not isinstance(resume, dict):
        return 0
    return _nonnegative(resume.get('resume_position_ms'))
