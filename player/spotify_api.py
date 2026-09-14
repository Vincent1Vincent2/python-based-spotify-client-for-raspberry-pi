"""
Custom Spotify API client - handles authentication and API requests directly.
"""
import requests
import time
import logging
from django.conf import settings
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class SpotifyAPI:
    """Custom Spotify API client."""
    
    BASE_URL = 'https://api.spotify.com/v1'
    AUTH_URL = 'https://accounts.spotify.com'
    
    def __init__(self, access_token=None):
        """Initialize with optional access token."""
        self.access_token = access_token
        self.client_id = settings.SPOTIFY_CLIENT_ID
        self.client_secret = settings.SPOTIFY_CLIENT_SECRET
        self.redirect_uri = settings.SPOTIFY_REDIRECT_URI
    
    def get_authorization_url(self, scope, state=None):
        """
        Generate Spotify authorization URL for OAuth flow.
        
        Args:
            scope: Space-separated string of Spotify scopes
            state: Optional state parameter for security
        
        Returns:
            Authorization URL string
        """
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'scope': scope,
        }
        
        if state:
            params['state'] = state
        
        url = f"{self.AUTH_URL}/authorize?{urlencode(params)}"
        return url
    
    def get_access_token(self, code):
        """
        Exchange authorization code for access token.
        
        Args:
            code: Authorization code from callback
        
        Returns:
            dict with token information (access_token, refresh_token, expires_in, etc.)
        """
        url = f"{self.AUTH_URL}/api/token"
        
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri,
        }
        
        auth = (self.client_id, self.client_secret)
        
        response = requests.post(url, data=data, auth=auth)
        response.raise_for_status()
        
        token_data = response.json()
        
        # Add expires_at timestamp for easier checking
        token_data['expires_at'] = time.time() + token_data.get('expires_in', 3600)
        
        return token_data
    
    def refresh_access_token(self, refresh_token):
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: Refresh token from previous authentication
        
        Returns:
            dict with new token information
        """
        url = f"{self.AUTH_URL}/api/token"
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }
        
        auth = (self.client_id, self.client_secret)
        
        response = requests.post(url, data=data, auth=auth)
        response.raise_for_status()
        
        token_data = response.json()
        
        # Add expires_at timestamp
        token_data['expires_at'] = time.time() + token_data.get('expires_in', 3600)
        
        # If refresh_token not in response, keep the old one
        if 'refresh_token' not in token_data:
            token_data['refresh_token'] = refresh_token
        
        return token_data
    
    def is_token_expired(self, token_info):
        """
        Check if token is expired or will expire soon (within 60 seconds).
        
        Args:
            token_info: dict with token information including expires_at
        
        Returns:
            bool: True if expired or expiring soon
        """
        if not token_info:
            return True
        
        expires_at = token_info.get('expires_at')
        if not expires_at:
            return True
        
        # Consider expired if less than 60 seconds remaining
        return time.time() >= (expires_at - 60)
    
    def _get_headers(self):
        """Get headers with authorization token."""
        if not self.access_token:
            raise ValueError("No access token available")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }
    
    def _request(self, method, endpoint, **kwargs):
        """
        Make authenticated API request.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for requests
        
        Returns:
            Response object
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        
        # Merge headers
        if 'headers' in kwargs:
            headers.update(kwargs['headers'])
            del kwargs['headers']
        
        response = requests.request(method, url, headers=headers, **kwargs)
        return response
    
    def get(self, endpoint, **kwargs):
        """GET request."""
        return self._request('GET', endpoint, **kwargs)
    
    def post(self, endpoint, **kwargs):
        """POST request."""
        return self._request('POST', endpoint, **kwargs)
    
    def put(self, endpoint, **kwargs):
        """PUT request."""
        return self._request('PUT', endpoint, **kwargs)
    
    def delete(self, endpoint, **kwargs):
        """DELETE request."""
        return self._request('DELETE', endpoint, **kwargs)
    
    # Helper methods for common Spotify API endpoints
    
    def get_devices(self):
        """Get available devices. Returns response object."""
        return self.get('me/player/devices')
    
    def get_current_playback(self, market=None, additional_types=None):
        """
        Get current playback state.
        
        Args:
            market: Optional ISO 3166-1 alpha-2 country code
            additional_types: Optional comma-separated list of item types (track, episode)
        
        Returns:
            Response object
        """
        params = {}
        if market:
            params['market'] = market
        if additional_types:
            params['additional_types'] = additional_types
        return self.get('me/player', params=params if params else None)
    
    def get_currently_playing(self, market=None, additional_types=None):
        """
        Get currently playing track/episode (simplified endpoint).
        
        Args:
            market: Optional ISO 3166-1 alpha-2 country code
            additional_types: Optional comma-separated list of item types (track, episode)
        
        Returns:
            Response object
        """
        params = {}
        if market:
            params['market'] = market
        if additional_types:
            params['additional_types'] = additional_types
        return self.get('me/player/currently-playing', params=params if params else None)
    
    def search(self, q, type='track', limit=20, offset=0):
        """
        Search for tracks, albums, artists, playlists.
        
        Args:
            q: Search query
            type: Comma-separated list of types (track, album, artist, playlist)
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {
            'q': q,
            'type': type,
            'limit': limit,
            'offset': offset
        }
        return self.get('search', params=params)
    
    def transfer_playback(self, device_id, force_play=False):
        """
        Transfer playback to a device.
        
        Args:
            device_id: Device ID to transfer to
            force_play: If True, start playing on the device
        
        Returns:
            Response object
        """
        data = {
            'device_ids': [device_id],
            'play': force_play
        }
        return self.put('me/player', json=data)
    
    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        """
        Start playback.
        
        Args:
            device_id: Optional device ID
            context_uri: URI of context to play (album, playlist, etc.)
            uris: List of track URIs to play
            offset: Offset for context (dict with 'position' or 'uri')
            position_ms: Optional starting position in ms - used when
                explicitly resuming a track/episode at the point it was
                at before a device transfer (see transfer_with_resume)
        
        Returns:
            Response object
        """
        data = {}
        if context_uri:
            data['context_uri'] = context_uri
        if uris:
            data['uris'] = uris
        if offset:
            data['offset'] = offset
        if position_ms is not None:
            data['position_ms'] = position_ms
        
        params = {}
        if device_id:
            params['device_id'] = device_id
        
        return self.put('me/player/play', json=data, params=params)

    def seek_playback(self, position_ms, device_id=None):
        """
        Seek to a position in the currently playing track/episode.

        Args:
            position_ms: Position in milliseconds to seek to
            device_id: Optional device ID

        Returns:
            Response object
        """
        params = {'position_ms': max(0, int(position_ms))}
        if device_id:
            params['device_id'] = device_id
        return self.put('me/player/seek', params=params)
    
    def pause_playback(self, device_id=None):
        """
        Pause playback.
        
        Args:
            device_id: Optional device ID
        
        Returns:
            Response object
        """
        params = {}
        if device_id:
            params['device_id'] = device_id
        return self.put('me/player/pause', params=params)
    
    def next_track(self, device_id=None):
        """
        Skip to next track.
        
        Args:
            device_id: Optional device ID
        
        Returns:
            Response object
        """
        params = {}
        if device_id:
            params['device_id'] = device_id
        return self.post('me/player/next', params=params)
    
    def previous_track(self, device_id=None):
        """
        Skip to previous track.
        
        Args:
            device_id: Optional device ID
        
        Returns:
            Response object
        """
        params = {}
        if device_id:
            params['device_id'] = device_id
        return self.post('me/player/previous', params=params)
    
    def add_to_queue(self, uri, device_id=None):
        """
        Add item to queue.
        
        Args:
            uri: Spotify URI of item to add
            device_id: Optional device ID
        
        Returns:
            Response object
        """
        params = {'uri': uri}
        if device_id:
            params['device_id'] = device_id
        return self.post('me/player/queue', params=params)
    
    def get_user_playlists(self, limit=50, offset=0):
        """
        Get current user's playlists.
        
        Args:
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get('me/playlists', params=params)
    
    def get_user_saved_albums(self, limit=50, offset=0):
        """
        Get current user's saved albums.
        
        Args:
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get('me/albums', params=params)
    
    def get_user_saved_tracks(self, limit=50, offset=0):
        """
        Get current user's saved tracks.
        
        Args:
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get('me/tracks', params=params)
    
    def get_categories(self, limit=50, offset=0):
        """
        Get browse categories.
        
        Args:
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get('browse/categories', params=params)
    
    def get_category_playlists(self, category_id, limit=50, offset=0):
        """
        Get playlists for a category.
        
        Args:
            category_id: Category ID
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get(f'browse/categories/{category_id}/playlists', params=params)
    
    def get_featured_playlists(self, limit=50, offset=0):
        """
        Get featured playlists.
        
        Args:
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get('browse/featured-playlists', params=params)
    
    def get_new_releases(self, limit=50, offset=0):
        """
        Get new releases.
        
        Args:
            limit: Number of results (max 50)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get('browse/new-releases', params=params)
    
    def get_recommendation_genre_seeds(self):
        """
        Get available genre seeds for recommendations.
        
        Returns:
            Response object
        """
        return self.get('recommendations/available-genre-seeds')
    
    def get_recommendations(self, seed_genres=None, seed_artists=None, seed_tracks=None, limit=20, **kwargs):
        """
        Get track recommendations.
        
        Args:
            seed_genres: List of genre seeds
            seed_artists: List of artist IDs
            seed_tracks: List of track IDs
            limit: Number of recommendations (max 100)
            **kwargs: Additional parameters (min_*, max_*, target_*)
        
        Returns:
            Response object
        """
        params = {'limit': limit}
        if seed_genres:
            params['seed_genres'] = ','.join(seed_genres)
        if seed_artists:
            params['seed_artists'] = ','.join(seed_artists)
        if seed_tracks:
            params['seed_tracks'] = ','.join(seed_tracks)
        params.update(kwargs)
        return self.get('recommendations', params=params)
    
    def get_album(self, album_id):
        """
        Get album by ID.
        
        Args:
            album_id: Album ID
        
        Returns:
            Response object
        """
        return self.get(f'albums/{album_id}')
    
    def get_playlist(self, playlist_id):
        """
        Get playlist by ID.
        
        Args:
            playlist_id: Playlist ID
        
        Returns:
            Response object
        """
        return self.get(f'playlists/{playlist_id}')
    
    def get_playlist_tracks(self, playlist_id, limit=100, offset=0):
        """
        Get tracks in a playlist.
        
        Args:
            playlist_id: Playlist ID
            limit: Number of results (max 100)
            offset: Offset for pagination
        
        Returns:
            Response object
        """
        params = {'limit': limit, 'offset': offset}
        return self.get(f'playlists/{playlist_id}/tracks', params=params)


def get_active_account(request):
    """
    Returns the SpotifyAccount currently active for this kiosk session,
    or None if nothing is linked/selected yet. This only resolves which
    row the session points at - it doesn't touch tokens (see
    get_spotify_api for that).
    """
    from .models import SpotifyAccount

    account_id = request.session.get('active_account_id')
    if not account_id:
        return None
    try:
        return SpotifyAccount.objects.get(id=account_id)
    except SpotifyAccount.DoesNotExist:
        # Session pointed at an account that's since been removed.
        request.session.pop('active_account_id', None)
        return None


def get_spotify_api(request):
    """
    Get a SpotifyAPI instance for the currently active LINKED ACCOUNT
    (not just whatever was last in the session), refreshing its token
    if needed and persisting the refresh back to that account's DB row.
    Persisting to the row (not only the session) is what lets switching
    between linked accounts, or restarting the server, keep working
    without re-running the OAuth flow each time.

    Returns None if there's no active account, or if its refresh token
    has stopped working (revoked/expired). In that case the account
    stays linked - it still shows up in the switcher - but is cleared
    as "active" so the UI can prompt to specifically reconnect it,
    rather than silently losing track of which account was in use.
    """
    account = get_active_account(request)
    if not account:
        return None

    api = SpotifyAPI()
    token_info = account.to_token_info()

    if api.is_token_expired(token_info):
        try:
            new_token_info = api.refresh_access_token(account.refresh_token)
            account.update_from_token_info(new_token_info)
            account.save()
            token_info = new_token_info
        except Exception:
            logger.warning("get_spotify_api: refresh failed for account id=%s", account.id, exc_info=True)
            request.session.pop('active_account_id', None)
            return None

    api.access_token = token_info['access_token']
    api.account_id = account.id  # lets callers know which account served this request
    return api


def fetch_spotify_profile(api):
    """
    GET /me for the account behind this SpotifyAPI instance. Used right
    after OAuth to identify which Spotify account was just authorized,
    so it can be linked (or matched to an existing linked account).
    """
    response = api.get('me')
    response.raise_for_status()
    return response.json()


def link_or_update_account(token_info, profile):
    """
    Create a SpotifyAccount for a newly-authorized Spotify user, or
    update the existing row if this Spotify account was already linked
    on this device before - re-authenticating a previously-linked
    account refreshes its stored tokens/profile instead of creating a
    duplicate.

    Returns the SpotifyAccount.
    """
    from .models import SpotifyAccount

    spotify_user_id = profile['id']
    images = profile.get('images') or []

    account, _created = SpotifyAccount.objects.update_or_create(
        spotify_user_id=spotify_user_id,
        defaults={
            'display_name': profile.get('display_name') or spotify_user_id,
            'email': profile.get('email', '') or '',
            'avatar_url': images[0]['url'] if images else '',
            'access_token': token_info['access_token'],
            'refresh_token': token_info['refresh_token'],
            'token_expires_at': token_info['expires_at'],
        },
    )
    return account


def capture_playback_snapshot(api):
    """
    Snapshot of what's currently playing (track/episode uri, context,
    progress, play state). Used to explicitly resume playback on a new
    device after a transfer, rather than hoping Spotify carries it over
    on its own.

    Returns None if nothing is playing or the snapshot can't be read -
    callers should treat that as "nothing to resume".
    """
    try:
        response = api.get_current_playback(additional_types='track,episode')
        if response.status_code == 204:
            return None
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.warning("capture_playback_snapshot: could not read current playback", exc_info=True)
        return None

    item = data.get('item')
    if not item:
        return None

    return {
        'is_playing': data.get('is_playing', False),
        'progress_ms': data.get('progress_ms', 0),
        'item_uri': item.get('uri'),
        'context_uri': (data.get('context') or {}).get('uri'),
    }


def transfer_with_resume(api, device_id, snapshot, max_attempts=4, poll_delay=0.6):
    """
    Transfer playback to device_id and verify it actually resumes
    there. Fixes the case where transfer_playback() succeeds but the
    new device sits transferred-and-silent instead of continuing
    playback (GitHub issue #3).

    Args:
        api: SpotifyAPI instance
        device_id: target device to transfer to
        snapshot: result of capture_playback_snapshot() taken BEFORE
            the transfer (or None if nothing was playing)
        max_attempts: how many times to poll for confirmation before
            falling back to an explicit restart
        poll_delay: seconds between polls

    Returns:
        dict: {
            'success': bool,
            'message': str,
            'resumed': bool,       # True if target device ended up playing
            'used_fallback': bool, # True if we had to explicitly restart
        }
    """
    was_playing = bool(snapshot and snapshot.get('is_playing'))

    # force_play mirrors what was happening before the transfer: don't
    # force a paused session to start playing, and do keep a playing
    # session playing.
    api.transfer_playback(device_id=device_id, force_play=was_playing)

    if not was_playing:
        return {
            'success': True,
            'message': 'Transferred (nothing was playing).',
            'resumed': False,
            'used_fallback': False,
        }

    # Poll to see if the target device actually picked up playback on
    # its own before we resort to an explicit restart.
    for _ in range(max_attempts):
        time.sleep(poll_delay)
        try:
            response = api.get_current_playback()
            if response.status_code == 200:
                data = response.json()
                active_device_id = (data.get('device') or {}).get('id')
                if data.get('is_playing') and active_device_id == device_id:
                    return {
                        'success': True,
                        'message': 'Transferred and resumed.',
                        'resumed': True,
                        'used_fallback': False,
                    }
        except Exception:
            logger.warning("transfer_with_resume: poll failed", exc_info=True)

    # Transfer didn't bring playback with it - explicitly restart at
    # the exact track/episode and position instead of leaving the
    # device transferred but silent.
    try:
        if snapshot.get('context_uri') and snapshot.get('item_uri'):
            api.start_playback(
                device_id=device_id,
                context_uri=snapshot['context_uri'],
                offset={'uri': snapshot['item_uri']},
                position_ms=snapshot.get('progress_ms', 0),
            )
        elif snapshot.get('item_uri'):
            api.start_playback(
                device_id=device_id,
                uris=[snapshot['item_uri']],
                position_ms=snapshot.get('progress_ms', 0),
            )
        else:
            api.start_playback(device_id=device_id)

        return {
            'success': True,
            'message': 'Transferred; explicitly resumed playback at the same position.',
            'resumed': True,
            'used_fallback': True,
        }
    except Exception as e:
        logger.warning("transfer_with_resume: fallback restart failed", exc_info=True)
        return {
            'success': False,
            'message': f'Transferred but could not resume playback: {e}',
            'resumed': False,
            'used_fallback': True,
        }