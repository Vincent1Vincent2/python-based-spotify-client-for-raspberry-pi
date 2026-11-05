import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase

from player.features.library_hearts.library import (
    LibraryError,
    LibraryScopeError,
    contains,
    remove,
    save,
)
from player.models import SpotifyAccount
from player.spotify_api import SpotifyAPI
from player.views import SPOTIFY_SCOPE


TRACK = 'spotify:track:abc'
ALBUM = 'spotify:album:def'
ORIGINAL_SCOPE = (
    'user-modify-playback-state user-read-playback-state '
    'user-read-currently-playing user-read-playback-position streaming '
    'playlist-read-private playlist-read-collaborative '
    'playlist-modify-private user-library-read'
)


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeAPI:
    def __init__(self, saved=None, status=200, payload=None):
        self.saved = {} if saved is None else saved
        self.status = status
        self.payload = payload
        self.calls = []

    def library_contains(self, uris):
        self.calls.append(('GET', '/me/library/contains', uris))
        if self.status >= 400:
            return FakeResponse({'error': {'message': 'Forbidden'}}, status=self.status)
        uri_list = uris.split(',') if isinstance(uris, str) else list(uris)
        return FakeResponse([bool(self.saved.get(uri)) for uri in uri_list])

    def save_library_items(self, uris):
        self.calls.append(('PUT', '/me/library', uris))
        if self.status >= 400:
            return FakeResponse(self.payload, status=self.status)
        for uri in uris.split(','):
            self.saved[uri] = True
        return FakeResponse(None, status=200)

    def remove_library_items(self, uris):
        self.calls.append(('DELETE', '/me/library', uris))
        if self.status >= 400:
            return FakeResponse(self.payload, status=self.status)
        for uri in uris.split(','):
            self.saved[uri] = False
        return FakeResponse(None, status=200)


class LibraryCallTests(TestCase):
    def test_track_and_album_share_one_contains_call(self):
        api = FakeAPI(saved={TRACK: True, ALBUM: False})
        result = contains(api, [TRACK, ALBUM])
        self.assertEqual(result, {'uris': [TRACK, ALBUM], 'saved': [True, False]})
        self.assertEqual(api.calls, [('GET', '/me/library/contains', f'{TRACK},{ALBUM}')])

    def test_contains_accepts_a_comma_separated_query(self):
        api = FakeAPI(saved={TRACK: False})
        result = contains(api, f'{TRACK},{TRACK}')
        self.assertEqual(result['uris'], [TRACK])
        self.assertEqual(len(api.calls), 1)

    def test_save_track_is_one_put(self):
        api = FakeAPI()
        result = save(api, TRACK)
        self.assertEqual(result['saved'], [True])
        self.assertEqual(api.calls, [('PUT', '/me/library', TRACK)])

    def test_save_album_is_one_put(self):
        api = FakeAPI()
        save(api, ALBUM)
        self.assertEqual(api.calls, [('PUT', '/me/library', ALBUM)])

    def test_remove_is_one_delete(self):
        api = FakeAPI(saved={TRACK: True, ALBUM: True})
        result = remove(api, [TRACK, ALBUM])
        self.assertEqual(result['saved'], [False, False])
        self.assertEqual(api.calls, [('DELETE', '/me/library', f'{TRACK},{ALBUM}')])

    def test_forbidden_library_call_needs_a_new_scope(self):
        api = FakeAPI(status=403)
        with self.assertRaises(LibraryScopeError) as raised:
            save(api, TRACK)
        self.assertEqual(raised.exception.code, 'needs_scope')
        with self.assertRaises(LibraryScopeError):
            contains(api, ALBUM)
        with self.assertRaises(LibraryScopeError):
            remove(api, TRACK)

    def test_artist_uris_are_rejected_without_a_spotify_call(self):
        api = FakeAPI()
        with self.assertRaises(LibraryError):
            contains(api, 'spotify:artist:abc')
        self.assertEqual(api.calls, [])

    def test_removed_track_routes_are_not_used(self):
        api = FakeAPI()
        contains(api, TRACK)
        save(api, ALBUM)
        remove(api, TRACK)
        for call in api.calls:
            self.assertNotIn('/me/tracks', call[1])
            self.assertNotIn('/me/albums', call[1])
            self.assertNotIn('recommendations', call[1])
            self.assertNotIn('audio-features', call[1])

    def test_more_than_forty_uris_are_not_split_into_calls(self):
        api = FakeAPI()
        uris = [f'spotify:track:{index}' for index in range(41)]
        with self.assertRaises(LibraryError):
            contains(api, uris)
        self.assertEqual(api.calls, [])


class SpotifyLibraryMethodTests(TestCase):
    def test_methods_use_library_query_uris_and_not_removed_routes(self):
        api = SpotifyAPI(access_token='token')
        with patch('player.spotify_api.requests.request') as request:
            request.return_value = FakeResponse([True, False])
            api.library_contains([TRACK, ALBUM])
            api.save_library_items(TRACK)
            api.remove_library_items(ALBUM)

        self.assertEqual(request.call_count, 3)
        contains_call, save_call, remove_call = request.call_args_list
        self.assertEqual(contains_call.args[0], 'GET')
        self.assertTrue(contains_call.args[1].endswith('/me/library/contains'))
        self.assertEqual(contains_call.kwargs['params']['uris'], f'{TRACK},{ALBUM}')
        self.assertEqual(save_call.args[0], 'PUT')
        self.assertTrue(save_call.args[1].endswith('/me/library'))
        self.assertNotIn('/contains', save_call.args[1])
        self.assertEqual(save_call.kwargs['params']['uris'], TRACK)
        self.assertNotIn('json', save_call.kwargs)
        self.assertEqual(remove_call.args[0], 'DELETE')
        self.assertTrue(remove_call.args[1].endswith('/me/library'))
        self.assertEqual(remove_call.kwargs['params']['uris'], ALBUM)
        self.assertNotIn('json', remove_call.kwargs)
        for call in request.call_args_list:
            self.assertNotIn('/me/tracks', call.args[1])
            self.assertNotIn('/me/albums', call.args[1])
            self.assertNotIn('recommendations', call.args[1])
            self.assertNotIn('audio-features', call.args[1])
            self.assertIn('Bearer token', call.kwargs['headers']['Authorization'])


class LibraryViewTests(TestCase):
    def _client(self, api):
        client = Client()
        patcher = patch(
            'player.features.library_hearts.views.get_spotify_api',
            return_value=api,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def test_contains_view_checks_track_and_album_once(self):
        api = FakeAPI(saved={TRACK: True, ALBUM: False})
        response = self._client(api).get(
            '/library/contains/',
            {'uris': f'{TRACK},{ALBUM}'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'uris': [TRACK, ALBUM], 'saved': [True, False]})
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0][0], 'GET')

    def test_put_saves_and_delete_removes(self):
        api = FakeAPI()
        client = self._client(api)
        saved = client.put(f'/library/items/?uris={TRACK}')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['saved'], [True])
        removed = client.delete(f'/library/items/?uris={ALBUM}')
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()['uris'], [ALBUM])
        self.assertEqual([call[0] for call in api.calls], ['PUT', 'DELETE'])

    def test_forbidden_response_is_needs_scope(self):
        api = FakeAPI(status=403)
        response = self._client(api).put(f'/library/items/?uris={TRACK}')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'needs_scope')
        self.assertIn('Reconnect Spotify', response.json()['error'])

    def test_missing_session_is_unauthorized(self):
        response = self._client(None).get('/library/contains/', {'uris': TRACK})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'token_expired')


class LibraryPageTests(TestCase):
    def test_scope_appends_library_modify_without_dropping_existing_scopes(self):
        self.assertTrue(SPOTIFY_SCOPE.startswith(ORIGINAL_SCOPE))
        self.assertIn('user-library-modify', SPOTIFY_SCOPE)
        self.assertIn('playlist-modify-private', SPOTIFY_SCOPE)
        self.assertLess(
            SPOTIFY_SCOPE.index('user-library-read'),
            SPOTIFY_SCOPE.index('user-library-modify'),
        )
        self.assertEqual(SPOTIFY_SCOPE.count('user-library-modify'), 1)

    def test_player_page_includes_the_heart_next_to_the_track(self):
        index_path = Path(settings.BASE_DIR) / 'player' / 'templates' / 'player' / 'index.html'
        source = index_path.read_text()
        self.assertIn(
            '<div class="track-info" id="trackInfo">\n'
            '                <div class="track-name">No track playing</div>\n'
            '                <div class="playback-context" id="playbackContext" hidden></div>\n'
            '            </div>\n'
            '            {% include "library_hearts/heart.html" %}\n',
            source,
        )
        self.assertEqual(source.count('library_hearts/heart.html'), 1)

        account = SpotifyAccount.objects.create(
            spotify_user_id='heart-user',
            display_name='Heart',
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
        body = page.content.decode()
        self.assertIn('id="libraryHeartTrack"', body)
        self.assertIn('id="libraryHeartAlbum"', body)
        self.assertIn('class="track-row library-heart-row"', body)
        self.assertIn('Save to Liked Songs', body)
        self.assertIn('Save album', body)
        self.assertIn('/library/contains/', body)
        self.assertIn('/library/items/', body)
        self.assertIn('/login/?auth=1', body)
        self.assertIn('renderLibraryHeartRows', body)

    def test_reconnect_starts_oauth_when_a_session_already_exists(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id='reconnect-user',
            display_name='Reconnect',
            access_token='access',
            refresh_token='refresh',
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session['active_account_id'] = account.id
        session.save()

        home = client.get('/login/')
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home.url, '/')

        reconnect = client.get('/login/?auth=1')
        self.assertEqual(reconnect.status_code, 302)
        self.assertIn('accounts.spotify.com/authorize', reconnect.url)
        self.assertIn('user-library-modify', reconnect.url)
        self.assertIn('playlist-modify-private', reconnect.url)

    def test_current_playback_includes_the_album_uri(self):
        api = FakeAPI()

        def get_current_playback(market=None, additional_types=None):
            return FakeResponse({
                'is_playing': True,
                'progress_ms': 5,
                'currently_playing_type': 'track',
                'device': {'id': 'dev', 'name': 'Pi', 'type': 'Speaker'},
                'context': {'uri': ALBUM},
                'item': {
                    'type': 'track',
                    'id': 'abc',
                    'uri': TRACK,
                    'name': 'Song',
                    'duration_ms': 1000,
                    'artists': [{'name': 'Ada'}],
                    'album': {'name': 'Record', 'uri': ALBUM, 'images': []},
                },
            })

        api.get_current_playback = get_current_playback
        with patch('player.views.get_spotify_api', return_value=api):
            response = Client().get('/current-playback/')
        self.assertEqual(response.status_code, 200)
        track = response.json()['track']
        self.assertEqual(track['uri'], TRACK)
        self.assertEqual(track['album_uri'], ALBUM)
