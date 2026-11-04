import inspect
import json
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from player.features.podcast_shelf.shelf import (
    PAGE_LIMIT,
    PodcastScopeError,
    PodcastShelfError,
    list_saved_shows,
    parse_show_reference,
    play_episode,
    remove_show,
    save_show,
    show_detail,
)
from player.models import SpotifyAccount
from player.spotify_api import SpotifyAPI
from player.views import SPOTIFY_SCOPE


ORIGINAL_SCOPE = (
    'user-modify-playback-state user-read-playback-state '
    'user-read-currently-playing user-read-playback-position streaming '
    'playlist-read-private playlist-read-collaborative '
    'playlist-modify-private user-library-read'
)


class FakeResponse:
    def __init__(self, payload=None, status=200, broken=False):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.broken = broken

    def json(self):
        if self.broken:
            raise ValueError('empty')
        return self._payload


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.saved = {'items': [], 'next': None, 'total': 0}
        self.show = {'id': 'show1', 'name': 'Daily'}
        self.episodes = {'items': [], 'next': None, 'total': 0}
        self.status = 200

    def __getattr__(self, name):
        raise AssertionError('unexpected Spotify call %s' % name)

    def get_saved_shows(self, limit=50, offset=0):
        self.calls.append(('get_saved_shows', limit, offset))
        return FakeResponse(self.saved, self.status)

    def get_show(self, show_id):
        self.calls.append(('get_show', show_id))
        return FakeResponse(self.show, self.status)

    def get_show_episodes(self, show_id, limit=50, offset=0):
        self.calls.append(('get_show_episodes', show_id, limit, offset))
        return FakeResponse(self.episodes, self.status)

    def save_show(self, show_id):
        self.calls.append(('save_show', show_id))
        return FakeResponse({}, self.status, broken=self.status < 400)

    def remove_show(self, show_id):
        self.calls.append(('remove_show', show_id))
        return FakeResponse({}, self.status, broken=self.status < 400)

    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        self.calls.append(('start_playback', {
            'device_id': device_id,
            'context_uri': context_uri,
            'uris': uris,
            'offset': offset,
            'position_ms': position_ms,
        }))
        status = 204 if self.status < 400 else self.status
        return FakeResponse({}, status, broken=True)


def _account(spotify_user_id):
    return SpotifyAccount.objects.create(
        spotify_user_id=spotify_user_id,
        display_name='Listener',
        access_token='access',
        refresh_token='refresh',
        token_expires_at=time.time() + 3600,
    )


def _client_for(account, **session):
    client = Client()
    stored = client.session
    stored['active_account_id'] = account.id
    stored['use_web_player'] = True
    stored.update(session)
    stored.save()
    return client


class ScopeTests(SimpleTestCase):
    def test_scope_appends_library_modify_and_keeps_the_rest(self):
        self.assertEqual(SPOTIFY_SCOPE, ORIGINAL_SCOPE + ' user-library-modify')
        scopes = SPOTIFY_SCOPE.split()
        self.assertEqual(len(scopes), len(set(scopes)))
        self.assertIn('playlist-modify-private', scopes)
        self.assertIn('user-library-read', scopes)
        self.assertEqual(scopes[-1], 'user-library-modify')


class ShowEndpointTests(SimpleTestCase):
    def test_saved_shows_and_one_show_use_single_pages(self):
        api = SpotifyAPI(access_token='token')
        with patch('player.spotify_api.requests.request') as request:
            request.return_value = FakeResponse({'items': []})
            api.get_saved_shows()
            api.get_saved_shows(limit=100, offset=-4)
            api.get_show('show1')
            api.get_show_episodes('show1')
            api.get_show_episodes('show1', limit=80, offset=50)
        calls = request.call_args_list
        self.assertEqual(calls[0].args, ('GET', 'https://api.spotify.com/v1/me/shows'))
        self.assertEqual(calls[0].kwargs['params'], {'limit': 50, 'offset': 0})
        self.assertEqual(calls[0].kwargs['headers']['Authorization'], 'Bearer token')
        self.assertEqual(calls[1].kwargs['params'], {'limit': 50, 'offset': 0})
        self.assertEqual(calls[2].args, ('GET', 'https://api.spotify.com/v1/shows/show1'))
        self.assertNotIn('params', calls[2].kwargs)
        self.assertEqual(calls[3].args, ('GET', 'https://api.spotify.com/v1/shows/show1/episodes'))
        self.assertEqual(calls[3].kwargs['params'], {'limit': 50, 'offset': 0})
        self.assertEqual(calls[4].kwargs['params'], {'limit': 50, 'offset': 50})

    def test_library_save_and_remove_send_one_show_uri(self):
        api = SpotifyAPI(access_token='token')
        with patch('player.spotify_api.requests.request') as request:
            request.return_value = FakeResponse({})
            api.save_show('show1')
            api.remove_show('show1')
        save, remove = request.call_args_list
        self.assertEqual(save.args, ('PUT', 'https://api.spotify.com/v1/me/library'))
        self.assertEqual(save.kwargs['params'], {'uris': 'spotify:show:show1'})
        self.assertNotIn('json', save.kwargs)
        self.assertNotIn(',', save.kwargs['params']['uris'])
        self.assertEqual(remove.args, ('DELETE', 'https://api.spotify.com/v1/me/library'))
        self.assertEqual(remove.kwargs['params'], {'uris': 'spotify:show:show1'})

    def test_batch_ids_never_leave_the_client(self):
        api = SpotifyAPI(access_token='token')
        with patch('player.spotify_api.requests.request') as request:
            for bad in ('abc,def', 'abc?ids=def', 'shows?ids=abc', '../me', '', 'spotify:show:abc'):
                with self.assertRaises(ValueError):
                    api.get_show(bad)
                with self.assertRaises(ValueError):
                    api.get_show_episodes(bad)
                with self.assertRaises(ValueError):
                    api.save_show(bad)
                with self.assertRaises(ValueError):
                    api.remove_show(bad)
        request.assert_not_called()

    def test_show_methods_do_not_name_batch_or_recommendation_endpoints(self):
        text = '\n'.join(inspect.getsource(method) for method in (
            SpotifyAPI.get_saved_shows,
            SpotifyAPI.get_show,
            SpotifyAPI.get_show_episodes,
            SpotifyAPI.save_show,
            SpotifyAPI.remove_show,
        ))
        self.assertNotIn('shows?ids', text)
        self.assertNotIn('episodes?ids', text)
        self.assertNotIn('recommendation', text.lower())
        self.assertIn('me/shows', text)
        self.assertIn('me/library', text)
        self.assertIn('spotify:show:', text)


class ShelfTests(SimpleTestCase):
    def test_page_limit_is_fifty(self):
        self.assertEqual(PAGE_LIMIT, 50)

    def test_saved_shows_keep_one_page_and_drop_bad_rows(self):
        api = FakeAPI()
        api.saved = {
            'items': [
                {'show': None},
                {'id': 'bare'},
                {
                    'show': {
                        'id': 'show1',
                        'name': 'Daily',
                        'publisher': 'Ada',
                        'description': 'Hello',
                        'explicit': True,
                        'total_episodes': 3,
                        'images': [{'url': 'https://i.scdn.co/image/cover'}],
                        'uri': 'javascript:alert(1)',
                        'html_description': '<b>Hello</b>',
                        'episodes': {'items': [{'id': 'hidden'}]},
                    },
                },
                {
                    'show': {
                        'id': 'show2',
                        'name': 'Nightly',
                        'images': [{'url': 'javascript:alert(1)'}],
                    },
                },
            ],
            'next': 'https://api.spotify.com/v1/me/shows?offset=50',
            'total': 8,
        }
        result = list_saved_shows(api, 0)
        self.assertEqual(api.calls, [('get_saved_shows', 50, 0)])
        self.assertEqual([show['id'] for show in result['shows']], ['show1', 'show2'])
        show = result['shows'][0]
        self.assertEqual(show, {
            'id': 'show1',
            'name': 'Daily',
            'publisher': 'Ada',
            'description': 'Hello',
            'image': 'https://i.scdn.co/image/cover',
            'total_episodes': 3,
            'uri': 'spotify:show:show1',
            'explicit': True,
        })
        self.assertIsNone(result['shows'][1]['image'])
        self.assertEqual(result['shows'][1]['uri'], 'spotify:show:show2')
        self.assertTrue(result['has_more'])
        self.assertEqual(result['limit'], 50)
        self.assertEqual(result['total'], 8)
        self.assertNotIn('html_description', show)
        self.assertNotIn('episodes', show)

    def test_detail_uses_the_episodes_page_not_the_embedded_list(self):
        api = FakeAPI()
        api.show = {
            'id': 'show1',
            'name': 'Daily',
            'publisher': 'Ada',
            'episodes': {'items': [{'id': 'embedded', 'name': 'No'}]},
        }
        api.episodes = {
            'items': [
                {
                    'id': 'ep1',
                    'name': 'Pilot',
                    'description': 'Start',
                    'duration_ms': 125000,
                    'release_date': '2024-01-02',
                    'explicit': False,
                    'images': [{'url': 'https://i.scdn.co/image/ep'}],
                    'resume_point': {'resume_position_ms': 5000, 'fully_played': False},
                    'uri': 'javascript:alert(1)',
                },
                {'id': ''},
                None,
            ],
            'next': None,
            'total': 1,
        }
        result = show_detail(api, 'show1', 0)
        self.assertEqual(api.calls, [
            ('get_show', 'show1'),
            ('get_show_episodes', 'show1', 50, 0),
        ])
        self.assertEqual(result['show']['name'], 'Daily')
        self.assertEqual(result['show']['uri'], 'spotify:show:show1')
        self.assertEqual(len(result['episodes']), 1)
        self.assertEqual(result['episodes'][0], {
            'id': 'ep1',
            'name': 'Pilot',
            'description': 'Start',
            'duration_ms': 125000,
            'release_date': '2024-01-02',
            'image': 'https://i.scdn.co/image/ep',
            'uri': 'spotify:episode:ep1',
            'explicit': False,
            'resume_position_ms': 5000,
        })
        self.assertFalse(result['has_more'])
        self.assertEqual(result['total'], 1)

    def test_later_pages_keep_the_same_limit(self):
        api = FakeAPI()
        list_saved_shows(api, 50)
        show_detail(api, 'show1', 50)
        self.assertEqual(api.calls[0], ('get_saved_shows', 50, 50))
        self.assertEqual(api.calls[-1], ('get_show_episodes', 'show1', 50, 50))

    def test_show_links_save_one_id(self):
        api = FakeAPI()
        saved = save_show(api, 'https://open.spotify.com/intl-en/show/abc123?si=zzz')
        self.assertEqual(saved['uri'], 'spotify:show:abc123')
        self.assertEqual(api.calls, [('save_show', 'abc123')])
        api.calls.clear()
        self.assertEqual(parse_show_reference('spotify:show:abc123'), 'abc123')
        self.assertEqual(parse_show_reference('  abc123  '), 'abc123')
        removed = remove_show(api, 'abc123')
        self.assertEqual(removed['uri'], 'spotify:show:abc123')
        self.assertEqual(api.calls, [('remove_show', 'abc123')])

    def test_save_rejects_a_list_or_another_kind_of_link(self):
        api = FakeAPI()
        for value in (
            '',
            'spotify:show:abc,spotify:show:def',
            'https://open.spotify.com/show/abc?ids=def',
            'https://open.spotify.com/episode/abc',
            'spotify:episode:abc',
            'spotify:track:abc',
        ):
            with self.assertRaises(PodcastShelfError):
                save_show(api, value)
        self.assertEqual(api.calls, [])

    def test_play_starts_that_episode_only(self):
        api = FakeAPI()
        result = play_episode(api, 'ep1', 'device1')
        self.assertEqual(result, {
            'status': 'playing',
            'episode_id': 'ep1',
            'uri': 'spotify:episode:ep1',
        })
        self.assertEqual(api.calls, [('start_playback', {
            'device_id': 'device1',
            'context_uri': None,
            'uris': ['spotify:episode:ep1'],
            'offset': None,
            'position_ms': None,
        })])
        api.calls.clear()
        play_episode(api, 'ep1', None)
        self.assertIsNone(api.calls[-1][1]['device_id'])
        self.assertEqual(api.calls[-1][1]['uris'], ['spotify:episode:ep1'])

    def test_forbidden_show_does_not_fetch_episodes(self):
        api = FakeAPI()
        api.status = 403
        with self.assertRaises(PodcastScopeError) as caught:
            show_detail(api, 'show1', 0)
        self.assertEqual(caught.exception.code, 'needs_scope')
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(api.calls, [('get_show', 'show1')])

    def test_forbidden_library_write_needs_a_new_scope(self):
        api = FakeAPI()
        api.status = 403
        with self.assertRaises(PodcastScopeError):
            save_show(api, 'show1')
        with self.assertRaises(PodcastScopeError):
            list_saved_shows(api, 0)
        self.assertEqual([call[0] for call in api.calls], ['save_show', 'get_saved_shows'])

    def test_other_spotify_errors_keep_their_status_out_of_the_scope_code(self):
        api = FakeAPI()
        api.status = 500
        api.saved = {'error': {'message': 'server'}}
        with self.assertRaises(PodcastShelfError) as caught:
            list_saved_shows(api, 0)
        self.assertEqual(caught.exception.code, 'podcast_error')
        self.assertEqual(caught.exception.status, 400)
        self.assertIn('Loading shows failed (500)', str(caught.exception))
        self.assertIn('server', str(caught.exception))

    def test_empty_write_body_still_counts_as_saved(self):
        api = FakeAPI()
        self.assertEqual(save_show(api, 'show1')['status'], 'saved')
        self.assertEqual(play_episode(api, 'ep9')['status'], 'playing')

    def test_offset_must_be_a_whole_number(self):
        from player.features.podcast_shelf.shelf import page_offset
        self.assertEqual(page_offset('50'), 50)
        with self.assertRaises(PodcastShelfError):
            page_offset('-1')
        with self.assertRaises(PodcastShelfError):
            page_offset('nope')


class PodcastWireTests(TestCase):
    def test_saved_shows_request_is_one_page_of_fifty(self):
        client = _client_for(_account('pod-list'))
        calls = []

        def fake_request(method, url, headers=None, **kwargs):
            calls.append((method, url, kwargs.get('params')))
            return FakeResponse({'items': [], 'next': None, 'total': 0})

        with patch('player.spotify_api.requests.request', fake_request):
            response = client.get('/shows/?limit=5&offset=50')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [
            ('GET', 'https://api.spotify.com/v1/me/shows', {'limit': 50, 'offset': 50}),
        ])
        self.assertEqual(response.json()['shows'], [])
        self.assertEqual(response.json()['limit'], 50)

    def test_detail_reads_the_show_and_then_its_episodes(self):
        client = _client_for(_account('pod-detail'))
        calls = []

        def fake_request(method, url, headers=None, **kwargs):
            calls.append((method, url, kwargs.get('params')))
            if url.endswith('/episodes'):
                return FakeResponse({
                    'items': [{
                        'id': 'ep1',
                        'name': 'Pilot',
                        'duration_ms': 1000,
                        'description': 'Start',
                    }],
                    'next': None,
                    'total': 1,
                })
            return FakeResponse({
                'id': 'show1',
                'name': 'Daily',
                'publisher': 'Ada',
                'html_description': '<b>nope</b>',
                'available_markets': ['US'],
                'episodes': {'items': [{'id': 'embedded', 'name': 'Hidden'}]},
            })

        with patch('player.spotify_api.requests.request', fake_request):
            response = client.get('/shows/detail/?id=show1&limit=20')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [
            ('GET', 'https://api.spotify.com/v1/shows/show1', None),
            ('GET', 'https://api.spotify.com/v1/shows/show1/episodes', {'limit': 50, 'offset': 0}),
        ])
        body = response.json()
        self.assertEqual(body['show']['uri'], 'spotify:show:show1')
        self.assertEqual([episode['id'] for episode in body['episodes']], ['ep1'])
        self.assertEqual(body['episodes'][0]['uri'], 'spotify:episode:ep1')
        encoded = response.content.decode()
        self.assertNotIn('embedded', encoded)
        self.assertNotIn('html_description', encoded)
        self.assertNotIn('available_markets', encoded)
        self.assertNotIn('recommendation', encoded.lower())

    def test_save_and_remove_use_the_library_uri(self):
        client = _client_for(_account('pod-save'))
        calls = []

        def fake_request(method, url, headers=None, **kwargs):
            calls.append((method, url, kwargs.get('params'), kwargs.get('json')))
            return FakeResponse({}, broken=True)

        with patch('player.spotify_api.requests.request', fake_request):
            saved = client.post(
                '/shows/save/',
                data=json.dumps({'show': 'https://open.spotify.com/show/abc123?si=zzz'}),
                content_type='application/json',
            )
            removed = client.post('/shows/remove/?id=abc123')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['uri'], 'spotify:show:abc123')
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()['status'], 'removed')
        self.assertEqual(calls, [
            ('PUT', 'https://api.spotify.com/v1/me/library', {'uris': 'spotify:show:abc123'}, None),
            ('DELETE', 'https://api.spotify.com/v1/me/library', {'uris': 'spotify:show:abc123'}, None),
        ])

    def test_play_episode_starts_that_episode_uri(self):
        client = _client_for(_account('pod-play'), use_web_player=False, selected_device_id='speaker')
        calls = []

        def fake_request(method, url, headers=None, **kwargs):
            calls.append((method, url, kwargs.get('params'), kwargs.get('json')))
            return FakeResponse({}, status=204, broken=True)

        with patch('player.spotify_api.requests.request', fake_request):
            played = client.post('/shows/play-episode/?id=ep1&device_id=query-device')
            client.post('/shows/play-episode/?id=ep2')
        self.assertEqual(played.status_code, 200)
        self.assertEqual(played.json()['uri'], 'spotify:episode:ep1')
        self.assertEqual(calls[0][0], 'PUT')
        self.assertEqual(calls[0][1], 'https://api.spotify.com/v1/me/player/play')
        self.assertEqual(calls[0][2], {'device_id': 'query-device'})
        self.assertEqual(calls[0][3], {'uris': ['spotify:episode:ep1']})
        self.assertNotIn('context_uri', calls[0][3])
        self.assertEqual(calls[1][2], {'device_id': 'speaker'})
        self.assertEqual(calls[1][3], {'uris': ['spotify:episode:ep2']})

    def test_web_player_device_comes_from_the_session(self):
        client = _client_for(
            _account('pod-web'),
            use_web_player=True,
            web_player_device_id='web-1',
            selected_device_id='speaker',
        )
        calls = []

        def fake_request(method, url, headers=None, **kwargs):
            calls.append(kwargs.get('params'))
            return FakeResponse({}, status=204, broken=True)

        with patch('player.spotify_api.requests.request', fake_request):
            response = client.post('/shows/play-episode/?id=ep1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [{'device_id': 'web-1'}])

    def test_forbidden_response_asks_for_a_new_scope(self):
        client = _client_for(_account('pod-forbidden'))

        def fake_request(method, url, headers=None, **kwargs):
            return FakeResponse({'error': {'message': 'Insufficient client scope'}}, 403)

        with patch('player.spotify_api.requests.request', fake_request):
            response = client.post(
                '/shows/save/',
                data=json.dumps({'id': 'show1'}),
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body['code'], 'needs_scope')
        self.assertEqual(body['login'], '/login/?auth=1')
        self.assertIn('Reconnect Spotify', body['error'])

    def test_bad_ids_do_not_call_spotify(self):
        client = _client_for(_account('pod-bad'))
        with patch('player.spotify_api.requests.request', side_effect=AssertionError('network')):
            detail = client.get('/shows/detail/?id=abc,def')
            saved = client.post(
                '/shows/save/',
                data=json.dumps({'show': 'spotify:show:abc,spotify:show:def'}),
                content_type='application/json',
            )
            played = client.post('/shows/play-episode/?id=spotify:episode:ep1')
            offset = client.get('/shows/?offset=nope')
        for response in (detail, saved, played, offset):
            self.assertEqual(response.status_code, 400)
            self.assertNotEqual(response.json().get('code'), 'needs_scope')
            self.assertNotIn('login', response.json())

    def test_missing_session_is_unauthorized(self):
        with patch('player.spotify_api.requests.request', side_effect=AssertionError('network')):
            listing = Client().get('/shows/')
            detail = Client().get('/shows/detail/?id=show1')
            played = Client().post('/shows/play-episode/?id=ep1')
        for response in (listing, detail, played):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['code'], 'token_expired')

    def test_invalid_json_is_rejected(self):
        client = _client_for(_account('pod-json'))
        with patch('player.spotify_api.requests.request', side_effect=AssertionError('network')):
            response = client.post(
                '/shows/save/',
                data='[',
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('JSON', response.json()['error'])


class PodcastPageTests(TestCase):
    def test_urls_and_index_include_the_shows_tab_once(self):
        root = Path(settings.BASE_DIR)
        urls = (root / 'player' / 'urls.py').read_text()
        index = (root / 'player' / 'templates' / 'player' / 'index.html').read_text()
        self.assertEqual(urls.count('include('), 1)
        self.assertIn("include('player.features.podcast_shelf.urls')", urls)
        self.assertEqual(index.count('{% include'), 1)
        self.assertIn(
            '<button class="tab-button" onclick="switchTab(\'feel\')" id="tab-feel">Feel</button>\n'
            '                    {% include "player/features/podcast_shelf/shows_tab.html" %}\n',
            index,
        )
        feature = root / 'player' / 'features' / 'podcast_shelf'
        banned = ('shows?ids', 'episodes?ids', 'get_recommendations', '/recommendations', 'feel_radio', 'player.feel')
        for path in feature.rglob('*'):
            if path.name == 'tests.py' or path.suffix not in {'.py', '.html', '.js', '.css'}:
                continue
            text = path.read_text()
            for term in banned:
                self.assertNotIn(term, text, '%s contains %s' % (path.name, term))

    def test_player_page_has_the_shows_tab(self):
        client = _client_for(_account('pod-page'))
        with patch('player.spotify_api.requests.request', side_effect=AssertionError('network')), \
                patch('player.spotify_api.SpotifyAPI.get_devices', return_value=FakeResponse({'devices': []})), \
                patch('player.spotify_api.SpotifyAPI.get_current_playback', return_value=FakeResponse({}, status=204)):
            page = client.get('/')
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="tab-shows"', body)
        self.assertIn('>Shows</button>', body)
        self.assertIn('id="content-shows"', body)
        self.assertIn('id="showsGrid"', body)
        self.assertIn('/shows/', body)
        self.assertIn('/shows/detail/', body)
        self.assertIn('/shows/save/', body)
        self.assertIn('/shows/remove/', body)
        self.assertIn('/shows/play-episode/', body)
        self.assertIn('/login/?auth=1', body)
        self.assertIn('Feel radio', body)
        self.assertNotIn('shows?ids', body)
        self.assertNotIn('episodes?ids', body)

    def test_logged_in_auth_link_starts_oauth_with_library_modify(self):
        client = _client_for(_account('pod-reauth'))
        with patch('player.spotify_api.requests.request', side_effect=AssertionError('network')):
            home = client.get('/login/')
            reconnect = client.get('/login/?auth=1')
            anonymous = Client().get('/login/?auth=1')
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home['Location'], '/')
        for response in (reconnect, anonymous):
            self.assertEqual(response.status_code, 302)
            location = response['Location']
            self.assertIn('https://accounts.spotify.com/authorize?', location)
            scopes = parse_qs(urlparse(location).query)['scope'][0].split()
            self.assertIn('user-library-modify', scopes)
            self.assertIn('playlist-modify-private', scopes)
            self.assertIn('user-library-read', scopes)
            self.assertEqual(scopes, (ORIGINAL_SCOPE + ' user-library-modify').split())
