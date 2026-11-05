import time
from unittest.mock import patch

from django.test import Client, TestCase

from player.features.context_chip.context import build_current_playback, context_label
from player.models import SpotifyAccount


def _playlist_playback():
    return {
        'is_playing': True,
        'currently_playing_type': 'track',
        'progress_ms': 1200,
        'device': {'id': 'device-1', 'name': 'Pi', 'type': 'Speaker'},
        'context': {
            'type': 'playlist',
            'uri': 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M',
            'href': 'https://api.spotify.com/v1/playlists/37i9dQZF1DXcBWIGoYBM5M',
            'external_urls': {
                'spotify': 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M',
            },
        },
        'item': {
            'type': 'track',
            'id': 'track1',
            'uri': 'spotify:track:track1',
            'name': 'Night Drive',
            'artists': [{'name': 'Ada'}],
            'album': {
                'name': 'Midnight',
                'images': [{'url': 'https://example.com/cover.jpg'}],
            },
            'duration_ms': 180000,
        },
    }


class _Response:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class _PlaybackAPI:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.calls = []

    def get_current_playback(self, additional_types=None):
        self.calls.append(additional_types)
        return _Response(self.payload, self.status)


class ContextLabelTests(TestCase):
    def test_maps_spotify_context_uris_and_null(self):
        self.assertEqual(context_label('spotify:playlist'), 'Playlist')
        self.assertEqual(context_label('spotify:album'), 'Album')
        self.assertEqual(context_label('spotify:artist'), 'Artist')
        self.assertIsNone(context_label(None))

    def test_show_and_full_uris(self):
        self.assertEqual(context_label('spotify:show'), 'Show')
        self.assertEqual(context_label('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'), 'Playlist')
        self.assertEqual(context_label('spotify:album:4aawyAB9vmqN3uQ7FjRGTy'), 'Album')
        self.assertIsNone(context_label('spotify:collection'))
        self.assertIsNone(context_label(''))


class PlaybackContextJsonTests(TestCase):
    def test_playlist_fixture_includes_type_and_uri_only(self):
        payload = build_current_playback(_playlist_playback())
        self.assertEqual(
            payload['context'],
            {
                'type': 'playlist',
                'uri': 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M',
            },
        )
        self.assertEqual(set(payload['context']), {'type', 'uri'})
        self.assertEqual(payload['track']['name'], 'Night Drive')
        self.assertEqual(payload['type'], 'track')

    def test_null_context_is_omitted(self):
        playback = _playlist_playback()
        playback['context'] = None
        payload = build_current_playback(playback)
        self.assertNotIn('context', payload)

        del playback['context']
        payload = build_current_playback(playback)
        self.assertNotIn('context', payload)

    def test_current_playback_returns_context_from_the_player_payload(self):
        api = _PlaybackAPI(_playlist_playback())
        with patch('player.views.get_spotify_api', return_value=api):
            response = Client().get('/current-playback/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body['context'],
            {
                'type': 'playlist',
                'uri': 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M',
            },
        )
        self.assertEqual(api.calls, ['track,episode'])
        self.assertNotIn('href', body['context'])


class ContextChipPageTests(TestCase):
    def test_player_page_has_a_hidden_context_line_under_the_title(self):
        account = SpotifyAccount.objects.create(
            spotify_user_id='context-user',
            display_name='Context',
            access_token='access',
            refresh_token='refresh',
            token_expires_at=time.time() + 3600,
        )
        client = Client()
        session = client.session
        session['active_account_id'] = account.id
        session['use_web_player'] = True
        session.save()

        with patch('player.spotify_api.SpotifyAPI.get_devices', return_value=_Response({'devices': []})), \
                patch('player.spotify_api.SpotifyAPI.get_current_playback', return_value=_Response({}, status=204)):
            page = client.get('/')
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="playbackContext"', body)
        self.assertIn('class="playback-context"', body)
        self.assertIn('renderPlaybackContext', body)
        self.assertIn("typeof viewPlaylist === 'function'", body)
        self.assertIn("typeof viewAlbum === 'function'", body)
        self.assertLess(
            body.index('class="track-name"'),
            body.index('id="playbackContext"'),
        )
