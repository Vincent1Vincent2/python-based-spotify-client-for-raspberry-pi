"""
Custom Spotify API client - handles authentication and API requests directly.
"""
import requests
import time
from django.conf import settings
from urllib.parse import urlencode


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
    
    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None):
        """
        Start playback.
        
        Args:
            device_id: Optional device ID
            context_uri: URI of context to play (album, playlist, etc.)
            uris: List of track URIs to play
            offset: Offset for context (dict with 'position' or 'uri')
        
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
        
        params = {}
        if device_id:
            params['device_id'] = device_id
        
        return self.put('me/player/play', json=data, params=params)
    
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


def get_spotify_api(request):
    """
    Get SpotifyAPI instance from session token info.
    Handles token refresh if needed.
    
    Args:
        request: Django request object
    
    Returns:
        SpotifyAPI instance or None if not authenticated
    """
    token_info = request.session.get('token_info', None)
    
    if not token_info:
        return None
    
    api = SpotifyAPI()
    
    # Check if token needs refresh
    if api.is_token_expired(token_info):
        try:
            refresh_token = token_info.get('refresh_token')
            if not refresh_token:
                return None
            
            # Refresh token
            new_token_info = api.refresh_access_token(refresh_token)
            
            # Update session
            request.session['token_info'] = new_token_info
            request.session.save()
            
            token_info = new_token_info
        except Exception as e:
            # Token refresh failed, clear session
            request.session.pop('token_info', None)
            return None
    
    # Create API instance with access token
    api.access_token = token_info['access_token']
    return api

