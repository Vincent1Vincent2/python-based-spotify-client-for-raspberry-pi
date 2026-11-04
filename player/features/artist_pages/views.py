"""Artist pages within Development Mode Spotify limits.

From one artist id the page reads:
  GET /artists/{id}
  GET /artists/{id}/albums?limit=10
  GET /search?q=artist:"Name"&type=track&limit=10
  GET /me/library/contains?uris=spotify:artist:{id}

Follow and unfollow are one call each:
  PUT or DELETE /me/library?uris=spotify:artist:{id}

Chart and similar-artist endpoints are not called. A 403 from Spotify
is returned as code needs_scope with a link back through /login/?auth=1.
"""
import json
import logging
import re

from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api


logger = logging.getLogger(__name__)

# Development Mode caps. Albums and search both stop at 10. Search text
# stops at 100 characters, the same cap Feel uses for a query string.
ALBUM_LIMIT = 10
TRACK_LIMIT = 10
QUERY_CHAR_LIMIT = 100
LOGIN_PATH = '/login/?auth=1'
ARTIST_ID = re.compile(r'^[A-Za-z0-9]{1,64}$')


class ArtistPageError(Exception):
    def __init__(self, message, code='artist_error', status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class ArtistScopeError(ArtistPageError):
    def __init__(self):
        super().__init__(
            'Reconnect Spotify to follow artists.',
            code='needs_scope',
            status=403,
        )


def artist_uri(artist_id):
    return f'spotify:artist:{artist_id}'


def track_search_query(name):
    """One search string: artist:"Name", never longer than 100 characters."""
    cleaned = ''.join(ch for ch in str(name or '') if ch not in '"\\')
    cleaned = ' '.join(cleaned.split())
    prefix = 'artist:"'
    suffix = '"'
    room = QUERY_CHAR_LIMIT - len(prefix) - len(suffix)
    if len(cleaned) > room:
        cleaned = cleaned[:room].rstrip()
    return f'{prefix}{cleaned}{suffix}'


def _status(response):
    return getattr(response, 'status_code', 200)


def _read(response):
    status = _status(response)
    if status == 401:
        raise ArtistPageError(
            'Not authenticated.',
            code='token_expired',
            status=401,
        )
    if status == 403:
        raise ArtistScopeError()
    if status == 404:
        raise ArtistPageError('Artist not found.', code='not_found', status=404)
    if status >= 400:
        raise ArtistPageError(
            f'Spotify returned {status}.',
            status=400 if status < 500 else 502,
        )
    if status == 204 or response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _image(images):
    if not isinstance(images, list) or not images:
        return ''
    first = images[0]
    if isinstance(first, dict):
        return first.get('url') or ''
    return ''


def _names(people):
    names = []
    for person in people or []:
        if isinstance(person, dict) and person.get('name'):
            names.append(person['name'])
        elif isinstance(person, str) and person:
            names.append(person)
    return names


def _year(value):
    text = str(value or '')
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return ''


def _total(payload):
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload.get('total'))
    except (TypeError, ValueError):
        return None


def format_duration(ms):
    try:
        ms = int(ms or 0)
    except (TypeError, ValueError):
        ms = 0
    if ms < 0:
        ms = 0
    seconds = ms // 1000
    return f'{seconds // 60}:{seconds % 60:02d}'


def shape_artist(artist, artist_id):
    name = artist.get('name') if isinstance(artist, dict) else ''
    name = (name or 'Unknown artist').strip() or 'Unknown artist'
    genres = []
    if isinstance(artist, dict):
        for genre in artist.get('genres') or []:
            if isinstance(genre, str) and genre:
                genres.append(genre)
    return {
        'id': artist_id,
        'name': name,
        'genres': genres,
        'image': _image(artist.get('images') if isinstance(artist, dict) else None),
        'uri': artist_uri(artist_id),
    }


_ALBUM_LABELS = {
    'album': 'Album',
    'single': 'Single',
    'compilation': 'Compilation',
    'appears_on': 'Appears on',
}


def shape_album(item):
    if not isinstance(item, dict) or not item.get('id'):
        return None
    album_type = item.get('album_type') or 'album'
    return {
        'id': item['id'],
        'name': item.get('name') or 'Untitled',
        'album_type': album_type,
        'type_label': _ALBUM_LABELS.get(album_type, album_type),
        'year': _year(item.get('release_date')),
        'total_tracks': item.get('total_tracks') or 0,
        'image': _image(item.get('images')),
        'uri': item.get('uri') or f"spotify:album:{item['id']}",
    }


def shape_track(item):
    if not isinstance(item, dict) or not item.get('id'):
        return None
    album = item.get('album') if isinstance(item.get('album'), dict) else {}
    return {
        'id': item['id'],
        'name': item.get('name') or 'Untitled',
        'uri': item.get('uri') or f"spotify:track:{item['id']}",
        'artists': _names(item.get('artists')),
        'album': album.get('name') or '',
        'image': _image(album.get('images')),
        'duration': format_duration(item.get('duration_ms')),
    }


def _shape_list(items, shaper, limit):
    shaped = []
    for item in items:
        row = shaper(item)
        if row:
            shaped.append(row)
        if len(shaped) >= limit:
            break
    return shaped


def _followed(payload):
    if isinstance(payload, list) and payload and payload[0] is True:
        return True
    if isinstance(payload, list) and payload and payload[0] is False:
        return False
    return False


def load_artist(api, artist_id):
    """Read one artist, one album page, one track search, and follow state.

    Stops after the artist read when that read fails, so a missing artist
    does not spend the album or search calls.
    """
    artist_payload = _read(api.get(f'artists/{artist_id}'))
    if not isinstance(artist_payload, dict) or not artist_payload.get('id'):
        raise ArtistPageError('Artist not found.', code='not_found', status=404)

    albums_payload = _read(api.get(
        f'artists/{artist_id}/albums',
        params={'limit': ALBUM_LIMIT},
    )) or {}
    album_items = albums_payload.get('items') if isinstance(albums_payload, dict) else None
    if not isinstance(album_items, list):
        album_items = []
    album_total = _total(albums_payload)
    if album_total is None and len(album_items) > ALBUM_LIMIT:
        album_total = len(album_items)

    query = track_search_query(artist_payload.get('name') or '')
    search_payload = _read(api.search(q=query, type='track', limit=TRACK_LIMIT)) or {}
    tracks_block = search_payload.get('tracks') if isinstance(search_payload, dict) else None
    if not isinstance(tracks_block, dict):
        tracks_block = {}
    track_items = tracks_block.get('items')
    if not isinstance(track_items, list):
        track_items = []
    track_total = _total(tracks_block)
    if track_total is None and len(track_items) > TRACK_LIMIT:
        track_total = len(track_items)

    needs_scope = False
    following = False
    try:
        contains = _read(api.get(
            'me/library/contains',
            params={'uris': artist_uri(artist_id)},
        ))
        following = _followed(contains)
    except ArtistScopeError:
        needs_scope = True
        following = None

    return {
        'artist': shape_artist(artist_payload, artist_id),
        'albums': _shape_list(album_items, shape_album, ALBUM_LIMIT),
        'album_total': album_total,
        'tracks': _shape_list(track_items, shape_track, TRACK_LIMIT),
        'track_total': track_total,
        'following': following,
        'needs_scope': needs_scope,
        'query': query,
    }


def set_artist_follow(api, artist_id, follow):
    """Follow with PUT, or unfollow with DELETE. One library call."""
    params = {'uris': artist_uri(artist_id)}
    if follow:
        response = api.put('me/library', params=params)
    else:
        response = api.delete('me/library', params=params)
    _read(response)
    return {
        'following': bool(follow),
        'artist_id': artist_id,
        'uri': params['uris'],
    }


def scope_denied_payload():
    return {
        'error': 'Reconnect Spotify to follow artists.',
        'code': 'needs_scope',
        'login_url': LOGIN_PATH,
        'link': f"<a href='{LOGIN_PATH}'>Reconnect Spotify</a>",
    }


def _render(request, context, status=200):
    context.setdefault('login_url', LOGIN_PATH)
    context.setdefault('artist', None)
    context.setdefault('needs_scope', False)
    context.setdefault('code', '')
    response = render(request, 'artist_pages/artist.html', context, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def _artist_id_from_request(request, artist_id=None):
    if artist_id:
        return str(artist_id).strip()
    raw = request.GET.get('id') or request.POST.get('id') or ''
    if raw:
        return str(raw).strip()
    if not request.body:
        return ''
    try:
        payload = json.loads(request.body.decode() or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ''
    if isinstance(payload, dict) and payload.get('id'):
        return str(payload['id']).strip()
    return ''


def artist_page(request, artist_id=None):
    """HTML artist page. Search opens this with ?id=. The detail route is /<id>/."""
    api = get_spotify_api(request)
    if not api:
        return redirect('login')

    raw_id = _artist_id_from_request(request, artist_id)
    if not raw_id:
        return _render(request, {})
    if not ARTIST_ID.match(raw_id):
        return _render(request, {
            'error': 'That artist id is not valid.',
            'code': 'bad_id',
        }, status=400)

    try:
        page = load_artist(api, raw_id)
    except ArtistScopeError as exc:
        logger.info('artist page needs a new Spotify login: %s', raw_id)
        return _render(request, {
            'error': str(exc),
            'code': exc.code,
            'needs_scope': True,
        }, status=403)
    except ArtistPageError as exc:
        return _render(request, {
            'error': str(exc),
            'code': exc.code,
            'needs_scope': isinstance(exc, ArtistScopeError),
        }, status=exc.status)
    except Exception:
        logger.exception('artist page failed for %s', raw_id)
        return _render(request, {
            'error': 'Spotify could not load this artist.',
            'code': 'spotify_error',
        }, status=502)

    if page['needs_scope']:
        page['code'] = 'needs_scope'
        page['error'] = 'Reconnect Spotify to follow artists.'
    return _render(request, page)


@csrf_exempt
@require_http_methods(['POST', 'PUT', 'DELETE'])
def artist_follow(request):
    """PUT follows the artist. DELETE unfollows. POST follows unless follow=0."""
    api = get_spotify_api(request)
    if not api:
        return JsonResponse(
            {'error': 'Not authenticated', 'code': 'token_expired'},
            status=401,
        )

    raw_id = _artist_id_from_request(request)
    if not ARTIST_ID.match(raw_id or ''):
        return JsonResponse({'error': 'Artist id required', 'code': 'bad_id'}, status=400)

    if request.method == 'DELETE':
        follow = False
    elif request.method == 'PUT':
        follow = True
    else:
        flag = request.POST.get('follow')
        if flag is None and request.body:
            try:
                payload = json.loads(request.body.decode() or '{}')
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and 'follow' in payload:
                flag = payload.get('follow')
        follow = str(flag if flag is not None else '1').lower() not in ('0', 'false', 'no')

    try:
        result = set_artist_follow(api, raw_id, follow)
    except ArtistScopeError:
        logger.info('artist follow needs a new Spotify login: %s', raw_id)
        response = JsonResponse(scope_denied_payload(), status=403)
        response['Cache-Control'] = 'no-store'
        return response
    except ArtistPageError as exc:
        return JsonResponse({'error': str(exc), 'code': exc.code}, status=exc.status)
    except Exception:
        logger.exception('artist follow failed for %s', raw_id)
        return JsonResponse(
            {'error': 'Spotify could not update this follow.', 'code': 'spotify_error'},
            status=502,
        )

    response = JsonResponse(result)
    response['Cache-Control'] = 'no-store'
    return response
