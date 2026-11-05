import json
import time
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from player.features.artist_pages.views import (
    ALBUM_LIMIT,
    QUERY_CHAR_LIMIT,
    TRACK_LIMIT,
    track_search_query,
)
from player.models import SpotifyAccount
from player.views import SPOTIFY_SCOPE


ARTIST_ID = '4Z8W4fKeB5YxbusRsdQVPb'
ORIGINAL_SCOPES = {
    'user-modify-playback-state',
    'user-read-playback-state',
    'user-read-currently-playing',
    'user-read-playback-position',
    'streaming',
    'playlist-read-private',
    'playlist-read-collaborative',
    'playlist-modify-private',
    'user-library-read',
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class FakeAPI:
    def __init__(self, artist=None, albums=None, tracks=None, following=False, status_for=None):
        self.artist = artist or {}
        self.albums = {'items': [], 'total': 0} if albums is None else albums
        self.tracks = tracks or []
        self.following = following
        self.status_for = status_for or {}
        self.calls = []

    def _status(self, endpoint):
        return self.status_for.get(endpoint, 200)

    def _record(self, method, endpoint, kwargs):
        extra = set(kwargs) - {'params'}
        if extra:
            raise AssertionError(f'unexpected Spotify options: {sorted(extra)}')
        self.calls.append((method, endpoint, kwargs.get('params')))

    def get(self, endpoint, **kwargs):
        self._record('GET', endpoint, kwargs)
        status = self._status(endpoint)
        if endpoint.endswith('/albums'):
            return FakeResponse(self.albums, status)
        if endpoint == 'me/library/contains':
            return FakeResponse([self.following], status)
        return FakeResponse(self.artist, status)

    def search(self, q, type='track', limit=20, offset=0, **kwargs):
        if kwargs:
            raise AssertionError(kwargs)
        self.calls.append(('GET', 'search', {
            'q': q,
            'type': type,
            'limit': limit,
            'offset': offset,
        }))
        return FakeResponse(
            {'tracks': {'items': self.tracks, 'total': len(self.tracks)}},
            self._status('search'),
        )

    def put(self, endpoint, **kwargs):
        self._record('PUT', endpoint, kwargs)
        return FakeResponse({}, self._status(endpoint))

    def delete(self, endpoint, **kwargs):
        self._record('DELETE', endpoint, kwargs)
        return FakeResponse({}, self._status(endpoint))


def _artist(name='Adele', artist_id=ARTIST_ID):
    return {
        'id': artist_id,
        'name': name,
        'genres': ['pop', 'soul'],
        'images': [{'url': 'https://i.scdn.co/image/adele', 'width': 640}],
    }


def _album(number):
    return {
        'id': f'album{number}',
        'name': f'Album {number}',
        'album_type': 'album',
        'release_date': '2011-01-24',
        'total_tracks': 11,
        'images': [{'url': f'https://i.scdn.co/image/album{number}'}],
        'uri': f'spotify:album:album{number}',
    }


def _track(number):
    return {
        'id': f'track{number}',
        'name': f'Song {number}',
        'uri': f'spotify:track:track{number}',
        'duration_ms': 228000,
        'artists': [{'name': 'Adele'}],
        'album': {'name': '21', 'images': [{'url': 'https://i.scdn.co/image/21'}]},
    }


class ArtistScopeTests(TestCase):
    def test_follow_scopes_are_added_without_dropping_current_scopes(self):
        parts = SPOTIFY_SCOPE.split()
        self.assertEqual(len(parts), len(set(parts)))
        scopes = set(parts)
        self.assertTrue(ORIGINAL_SCOPES <= scopes)
        self.assertTrue({'user-follow-modify', 'user-follow-read'} <= scopes)
        self.assertEqual(ALBUM_LIMIT, 10)
        self.assertEqual(TRACK_LIMIT, 10)
        self.assertEqual(QUERY_CHAR_LIMIT, 100)

    def test_login_asks_spotify_for_the_same_scope_string(self):
        response = self.client.get('/login/?auth=1')
        self.assertEqual(response.status_code, 302)
        location = response['Location']
        for scope in ORIGINAL_SCOPES | {'user-follow-modify', 'user-follow-read'}:
            self.assertIn(scope, location)

    def test_feature_source_does_not_use_removed_endpoints(self):
        root = Path(__file__).resolve().parent
        chunks = []
        for path in root.rglob('*'):
            if path.suffix in {'.py', '.html', '.css'} and path.name != 'tests.py':
                chunks.append(path.read_text(encoding='utf-8'))
        blob = '\n'.join(chunks).lower()
        self.assertNotIn('spotipy', blob)
        self.assertNotIn('top-tracks', blob)
        self.assertNotIn('related-artists', blob)
        self.assertNotIn('related_artists', blob)
        self.assertNotIn('/me/following', blob)
        self.assertNotIn('import requests', blob)
        urls = (root.parents[1] / 'urls.py').read_text(encoding='utf-8')
        self.assertEqual(urls.count("include('player.features.artist_pages.urls')"), 1)
        self.assertEqual(urls.count('artist-pages'), 1)


class ArtistPageTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _api(self, **kwargs):
        artist = kwargs.pop('artist', None) or _artist()
        albums = kwargs.pop('albums', None)
        if albums is None:
            albums = {'items': [_album(1)], 'total': 1}
        tracks = kwargs.pop('tracks', None)
        if tracks is None:
            tracks = [_track(1)]
        return FakeAPI(artist=artist, albums=albums, tracks=tracks, **kwargs)

    def _open(self, api, url):
        with patch('player.features.artist_pages.views.get_spotify_api', return_value=api), \
                patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
            return self.client.get(url)

    def _send(self, api, method, url):
        with patch('player.features.artist_pages.views.get_spotify_api', return_value=api), \
                patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
            return getattr(self.client, method)(url)

    def _assert_budget(self, api, name='Adele', query=None):
        self.assertEqual([call[0] for call in api.calls], ['GET', 'GET', 'GET', 'GET'])
        self.assertEqual([call[1] for call in api.calls], [
            f'artists/{ARTIST_ID}',
            f'artists/{ARTIST_ID}/albums',
            'search',
            'me/library/contains',
        ])
        self.assertIsNone(api.calls[0][2])
        self.assertEqual(api.calls[1][2], {'limit': 10})
        self.assertEqual(api.calls[2][2]['type'], 'track')
        self.assertEqual(api.calls[2][2]['limit'], 10)
        self.assertEqual(api.calls[2][2]['offset'], 0)
        self.assertEqual(api.calls[2][2]['q'], query or f'artist:"{name}"')
        self.assertLessEqual(len(api.calls[2][2]['q']), 100)
        self.assertEqual(api.calls[3][2], {'uris': f'spotify:artist:{ARTIST_ID}'})
        for _method, endpoint, params in api.calls:
            haystack = f'{endpoint} {json.dumps(params or {})}'
            self.assertNotIn('top-tracks', haystack)
            self.assertNotIn('related-artists', haystack)
            self.assertNotIn('following', haystack)
            self.assertNotIn('recommendations', haystack)
            if params and 'limit' in params:
                self.assertEqual(params['limit'], 10)

    def test_search_result_can_open_the_artist_page(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id='artist-page-user',
            display_name='Page',
            access_token='access',
            refresh_token='refresh',
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session['active_account_id'] = account.id
        session['use_web_player'] = True
        session.save()
        with patch('player.spotify_api.SpotifyAPI.get_devices', return_value=FakeResponse({'devices': []})), \
                patch('player.spotify_api.SpotifyAPI.get_current_playback', return_value=FakeResponse({}, status=204)):
            page = client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '/features/artist-pages/?id=')
        self.assertContains(page, 'encodeURIComponent(artist.id)')

    def test_query_and_detail_route_use_one_album_page_and_one_search(self):
        urls = (
            f'/features/artist-pages/?id={ARTIST_ID}',
            f'/features/artist-pages/{ARTIST_ID}/',
        )
        self.assertEqual(reverse('artist_pages:artist_page'), '/features/artist-pages/')
        self.assertEqual(
            reverse('artist_pages:artist_detail', args=[ARTIST_ID]),
            f'/features/artist-pages/{ARTIST_ID}/',
        )
        for url in urls:
            api = self._api(
                albums={'items': [_album(i) for i in range(12)], 'total': 40},
                tracks=[_track(i) for i in range(12)],
            )
            response = self._open(api, url)
            self.assertEqual(response.status_code, 200)
            self._assert_budget(api)
            body = response.content.decode()
            self.assertEqual(body.count('class="artist-album"'), 10)
            self.assertEqual(body.count('class="artist-track"'), 10)
            self.assertIn('Adele', body)
            self.assertIn('pop, soul', body)
            self.assertIn('3:48', body)
            self.assertIn(f'href="/features/artist-pages/{ARTIST_ID}/"', body)
            self.assertIn('artist_pages/artist.css', body)
            self.assertIn('Songs', body)
            self.assertIn('Albums', body)
            self.assertNotIn('followers', body)
            self.assertNotIn('href="/login/?auth=1"', body)
            self.assertContains(response, '>Follow<')

    def test_quoted_and_long_names_stay_inside_one_search(self):
        self.assertEqual(track_search_query('Weird "Al" Yankovic'), 'artist:"Weird Al Yankovic"')
        long_name = 'Y' * 200
        query = track_search_query(long_name)
        self.assertEqual(len(query), 100)
        self.assertTrue(query.startswith('artist:"'))
        self.assertTrue(query.endswith('"'))

        api = self._api(artist=_artist(name='Weird "Al" Yankovic'))
        response = self._open(api, f'/features/artist-pages/?id={ARTIST_ID}')
        self.assertEqual(response.status_code, 200)
        self._assert_budget(api, query='artist:"Weird Al Yankovic"')
        self.assertContains(response, 'Weird &quot;Al&quot; Yankovic')

        api = self._api(artist=_artist(name=long_name))
        response = self._open(api, f'/features/artist-pages/?id={ARTIST_ID}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(api.calls[2][2]['q'], query)
        self.assertEqual(len([call for call in api.calls if call[1] == 'search']), 1)

    def test_missing_artist_stops_after_the_artist_read(self):
        api = self._api(status_for={f'artists/{ARTIST_ID}': 404})
        response = self._open(api, f'/features/artist-pages/?id={ARTIST_ID}')
        self.assertEqual(response.status_code, 404)
        self.assertEqual([call[1] for call in api.calls], [f'artists/{ARTIST_ID}'])
        self.assertContains(response, 'Artist not found.', status_code=404)

    def test_blank_or_invalid_id_does_not_call_spotify(self):
        api = self._api()
        blank = self._open(api, '/features/artist-pages/')
        self.assertEqual(blank.status_code, 200)
        self.assertContains(blank, 'name="id"')
        self.assertEqual(api.calls, [])

        api = self._api()
        invalid = self._open(api, '/features/artist-pages/ab_cd/')
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(api.calls, [])

    def test_library_contains_forbidden_still_shows_the_artist_and_login_link(self):
        api = self._api(status_for={'me/library/contains': 403})
        response = self._open(api, f'/features/artist-pages/?id={ARTIST_ID}')
        self.assertEqual(response.status_code, 200)
        self._assert_budget(api)
        self.assertContains(response, 'needs_scope')
        self.assertContains(response, 'href="/login/?auth=1"')
        self.assertContains(response, 'Adele')
        self.assertNotContains(response, 'id="artistFollow"')

    def test_artist_forbidden_returns_needs_scope_and_login_link(self):
        api = self._api(status_for={f'artists/{ARTIST_ID}': 403})
        response = self._open(api, f'/features/artist-pages/{ARTIST_ID}/')
        self.assertEqual(response.status_code, 403)
        self.assertEqual([call[1] for call in api.calls], [f'artists/{ARTIST_ID}'])
        body = response.content.decode()
        self.assertIn('needs_scope', body)
        self.assertIn('<a href="/login/?auth=1">', body)
        self.assertIn('Reconnect Spotify', body)

    def test_follow_puts_and_unfollow_deletes_one_library_uri(self):
        api = self._api()
        followed = self._send(api, 'put', f'/features/artist-pages/follow/?id={ARTIST_ID}')
        self.assertEqual(followed.status_code, 200)
        self.assertEqual(followed.json()['following'], True)
        self.assertEqual(api.calls, [
            ('PUT', 'me/library', {'uris': f'spotify:artist:{ARTIST_ID}'}),
        ])

        api = self._api()
        unfollowed = self._send(api, 'delete', f'/features/artist-pages/follow/?id={ARTIST_ID}')
        self.assertEqual(unfollowed.status_code, 200)
        self.assertEqual(unfollowed.json()['following'], False)
        self.assertEqual(api.calls, [
            ('DELETE', 'me/library', {'uris': f'spotify:artist:{ARTIST_ID}'}),
        ])

    def test_follow_forbidden_returns_needs_scope_and_login_link(self):
        api = self._api(status_for={'me/library': 403})
        response = self._send(api, 'put', f'/features/artist-pages/follow/?id={ARTIST_ID}')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(api.calls, [
            ('PUT', 'me/library', {'uris': f'spotify:artist:{ARTIST_ID}'}),
        ])
        payload = response.json()
        self.assertEqual(payload['code'], 'needs_scope')
        self.assertEqual(payload['login_url'], '/login/?auth=1')
        body = response.content.decode()
        self.assertIn('needs_scope', body)
        self.assertIn('/login/?auth=1', body)
        self.assertIn("<a href='/login/?auth=1'>", body)

    def test_page_and_follow_require_a_session(self):
        with patch('player.features.artist_pages.views.get_spotify_api', return_value=None):
            page = self.client.get(f'/features/artist-pages/?id={ARTIST_ID}')
            follow = self.client.put(f'/features/artist-pages/follow/?id={ARTIST_ID}')
        self.assertEqual(page.status_code, 302)
        self.assertIn('/login', page['Location'])
        self.assertEqual(follow.status_code, 401)
        self.assertEqual(follow.json()['code'], 'token_expired')

    def test_following_button_uses_the_library_flag(self):
        api = self._api(following=True)
        response = self._open(api, f'/features/artist-pages/?id={ARTIST_ID}')
        self.assertContains(response, '>Following<')
        self.assertContains(response, 'data-following="true"')
