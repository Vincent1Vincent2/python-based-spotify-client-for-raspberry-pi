import spotipy
from spotipy.oauth2 import SpotifyOAuth
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json


SPOTIFY_SCOPE = 'user-modify-playback-state user-read-playback-state user-read-currently-playing user-read-playback-position streaming playlist-read-private playlist-read-collaborative'


def get_spotify_client(request):
    """Get or create Spotify client from session."""
    token_info = request.session.get('token_info', None)
    
    if not token_info:
        return None
    
    auth_manager = SpotifyOAuth(
        client_id=settings.SPOTIPY_CLIENT_ID,
        client_secret=settings.SPOTIPY_CLIENT_SECRET,
        redirect_uri=settings.SPOTIPY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE
    )
    
    if auth_manager.is_token_expired(token_info):
        token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
        request.session['token_info'] = token_info
    
    return spotipy.Spotify(auth=token_info['access_token'])


def index(request):
    """Main player interface."""
    sp = get_spotify_client(request)
    
    if not sp:
        return redirect('login')
    
    try:
        token_info = request.session.get('token_info', None)
        access_token = token_info.get('access_token') if token_info else None
        
        # Get available devices
        devices_list = sp.devices()
        selected_device_id = request.session.get('selected_device_id', None)
        use_web_player = request.session.get('use_web_player', True)
        manual_selection = request.session.get('manual_device_selection', False)
        
        # Only auto-sync if user hasn't manually selected a device
        # This prevents auto-switching back after manual transfer
        if not manual_selection:
            # Check which device is actually playing
            try:
                playback = sp.current_playback()
                if playback and playback.get('device'):
                    active_device_id = playback['device']['id']
                    # If a device is actively playing, sync session to match
                    device_found = False
                    for device in devices_list.get('devices', []):
                        if device['id'] == active_device_id:
                            device_found = True
                            break
                    
                    if device_found:
                        # Device is playing, so set it as selected (not web player)
                        selected_device_id = active_device_id
                        use_web_player = False
                        request.session['selected_device_id'] = active_device_id
                        request.session['use_web_player'] = False
            except Exception:
                # If we can't get playback info, use session values
                pass
        
        context = {
            'access_token': access_token,
            'client_id': settings.SPOTIPY_CLIENT_ID,
            'devices': devices_list.get('devices', []),
            'selected_device_id': selected_device_id,
            'use_web_player': use_web_player,
        }
    except Exception as e:
        context = {
            'error': str(e), 
            'access_token': None, 
            'client_id': settings.SPOTIPY_CLIENT_ID,
            'devices': [],
            'selected_device_id': None,
            'use_web_player': True,
        }
    
    return render(request, 'player/index.html', context)


def login_view(request):
    """Show login page or initiate Spotify OAuth login."""
    # If already authenticated, redirect to index
    sp = get_spotify_client(request)
    if sp:
        return redirect('index')
    
    # If 'auth' parameter is present, initiate OAuth flow
    if request.GET.get('auth') == '1':
        auth_manager = SpotifyOAuth(
            client_id=settings.SPOTIPY_CLIENT_ID,
            client_secret=settings.SPOTIPY_CLIENT_SECRET,
            redirect_uri=settings.SPOTIPY_REDIRECT_URI,
            scope=SPOTIFY_SCOPE
        )
        
        auth_url = auth_manager.get_authorize_url()
        return redirect(auth_url)
    
    # Otherwise show login page
    return render(request, 'player/login.html')


def logout_view(request):
    """Logout and clear session."""
    request.session.flush()
    return redirect('login')


def callback(request):
    """Handle Spotify OAuth callback."""
    code = request.GET.get('code')
    error = request.GET.get('error')
    
    if error:
        return render(request, 'player/error.html', {'error': error})
    
    auth_manager = SpotifyOAuth(
        client_id=settings.SPOTIPY_CLIENT_ID,
        client_secret=settings.SPOTIPY_CLIENT_SECRET,
        redirect_uri=settings.SPOTIPY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE
    )
    
    token_info = auth_manager.get_access_token(code)
    request.session['token_info'] = token_info
    request.session['use_web_player'] = True  # Default to web player
    
    return redirect('index')


def token(request):
    """Get access token for Web Playback SDK."""
    token_info = request.session.get('token_info', None)
    if not token_info:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    # Refresh token if needed
    auth_manager = SpotifyOAuth(
        client_id=settings.SPOTIPY_CLIENT_ID,
        client_secret=settings.SPOTIPY_CLIENT_SECRET,
        redirect_uri=settings.SPOTIPY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE
    )
    
    if auth_manager.is_token_expired(token_info):
        token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
        request.session['token_info'] = token_info
    
    return JsonResponse({'access_token': token_info.get('access_token')})


def search(request):
    """Search for tracks."""
    query = request.GET.get('q', '')
    if not query:
        return JsonResponse({'error': 'Query parameter required'}, status=400)
    
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        results = sp.search(q=query, type='track', limit=10)
        tracks = [{
            'id': item['id'],
            'name': item['name'],
            'artists': [artist['name'] for artist in item['artists']],
            'album': item['album']['name'],
            'image': item['album']['images'][-1]['url'] if item['album']['images'] else None,
        } for item in results['tracks']['items']]
        return JsonResponse({'tracks': tracks})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def devices(request):
    """Get available devices."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        devices_list = sp.devices()
        device_list = [{
            'id': device['id'],
            'name': device['name'],
            'type': device['type'],
            'is_active': device.get('is_active', False),
            'volume': device.get('volume_percent', 0),
        } for device in devices_list.get('devices', [])]
        return JsonResponse({'devices': device_list})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def transfer_device(request):
    """Transfer playback to a specific device."""
    device_id = request.GET.get('device_id', '')
    if not device_id:
        return JsonResponse({'error': 'Device ID required'}, status=400)
    
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        # Verify device exists and is available
        devices_list = sp.devices()
        device_found = False
        for device in devices_list.get('devices', []):
            if device['id'] == device_id:
                device_found = True
                break
        
        if not device_found:
            return JsonResponse({'error': 'Device not found or not available'}, status=404)
        
        # Transfer playback to this device
        sp.transfer_playback(device_id=device_id, force_play=False)
        
        # Save as selected device in session and mark as manual selection
        request.session['selected_device_id'] = device_id
        request.session['use_web_player'] = False
        request.session['manual_device_selection'] = True  # Prevent auto-switching
        
        return JsonResponse({'status': 'transferred', 'device_id': device_id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def select_web_player(request):
    """Select the Web Playback SDK player as the active device."""
    device_id = request.GET.get('device_id', '')
    
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    # If device_id is provided (from Web Playback SDK), transfer to it
    if device_id:
        try:
            # First verify the device exists
            devices_list = sp.devices()
            device_found = False
            for device in devices_list.get('devices', []):
                if device['id'] == device_id:
                    device_found = True
                    break
            
            if not device_found:
                # Web player device might not be in the list yet, but that's okay
                # It should still be available for transfer
                pass
            
            # Transfer playback to the web player device and resume playback
            # Use force_play=True to continue playing after transfer
            sp.transfer_playback(device_id=device_id, force_play=True)
            request.session['web_player_device_id'] = device_id
            request.session['manual_device_selection'] = True  # Set this BEFORE other session updates
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    request.session['use_web_player'] = True
    request.session['selected_device_id'] = None
    request.session['manual_device_selection'] = True  # Prevent auto-switching
    request.session.save()  # Explicitly save session
    return JsonResponse({'status': 'selected', 'device': 'web_player'})


@csrf_exempt
@require_http_methods(["POST"])
def play(request):
    """Start playback on selected device (REST API only, for non-web-player devices)."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    use_web_player = request.session.get('use_web_player', True)
    if use_web_player:
        return JsonResponse({'error': 'Use Web Playback SDK for web player'}, status=400)
    
    try:
        device_id = request.session.get('selected_device_id')
        if not device_id:
            return JsonResponse({'error': 'No device selected'}, status=400)
        
        sp.transfer_playback(device_id=device_id, force_play=False)
        sp.start_playback(device_id=device_id)
        return JsonResponse({'status': 'playing', 'device_id': device_id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def pause(request):
    """Pause playback (REST API only, for non-web-player devices)."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    use_web_player = request.session.get('use_web_player', True)
    if use_web_player:
        return JsonResponse({'error': 'Use Web Playback SDK for web player'}, status=400)
    
    try:
        device_id = request.session.get('selected_device_id')
        sp.pause_playback(device_id=device_id if device_id else None)
        return JsonResponse({'status': 'paused'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def next_track(request):
    """Skip to next track (REST API only, for non-web-player devices)."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    use_web_player = request.session.get('use_web_player', True)
    if use_web_player:
        return JsonResponse({'error': 'Use Web Playback SDK for web player'}, status=400)
    
    try:
        device_id = request.session.get('selected_device_id')
        sp.next_track(device_id=device_id if device_id else None)
        return JsonResponse({'status': 'next'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def previous_track(request):
    """Skip to previous track (REST API only, for non-web-player devices)."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    use_web_player = request.session.get('use_web_player', True)
    if use_web_player:
        return JsonResponse({'error': 'Use Web Playback SDK for web player'}, status=400)
    
    try:
        device_id = request.session.get('selected_device_id')
        sp.previous_track(device_id=device_id if device_id else None)
        return JsonResponse({'status': 'previous'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def queue_track(request):
    """Add track to queue."""
    track_id = request.GET.get('id', '')
    if not track_id:
        return JsonResponse({'error': 'Track ID required'}, status=400)
    
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        use_web_player = request.session.get('use_web_player', True)
        device_id = None if use_web_player else request.session.get('selected_device_id')
        sp.add_to_queue(f'spotify:track:{track_id}', device_id=device_id)
        return JsonResponse({'status': 'queued'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def playlists(request):
    """Get user's playlists."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        playlists_list = []
        results = sp.current_user_playlists(limit=50)
        
        while results:
            for playlist in results['items']:
                playlists_list.append({
                    'id': playlist['id'],
                    'name': playlist['name'],
                    'description': playlist.get('description', ''),
                    'image': playlist['images'][0]['url'] if playlist['images'] else None,
                    'tracks_count': playlist['tracks']['total'],
                    'owner': playlist['owner']['display_name'] or playlist['owner']['id'],
                    'public': playlist.get('public', False),
                    'collaborative': playlist.get('collaborative', False),
                })
            
            if results['next']:
                results = sp.next(results)
            else:
                break
        
        # Keep playlists in the original order from Spotify API
        # This matches the order shown in the Spotify app (pinned playlists come first)
        return JsonResponse({'playlists': playlists_list})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def playlist_detail(request):
    """Get detailed information about a specific playlist including tracks."""
    playlist_id = request.GET.get('id', '')
    if not playlist_id:
        return JsonResponse({'error': 'Playlist ID required'}, status=400)
    
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        # Get playlist details
        playlist = sp.playlist(playlist_id)
        
        # Get all tracks in the playlist
        tracks_list = []
        results = sp.playlist_tracks(playlist_id, limit=100)
        
        while results:
            for item in results['items']:
                if item.get('track') and item['track']:  # Some tracks may be None
                    track = item['track']
                    tracks_list.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artists': [artist['name'] for artist in track['artists']],
                        'album': track['album']['name'],
                        'image': track['album']['images'][-1]['url'] if track['album']['images'] else None,
                        'duration_ms': track.get('duration_ms', 0),
                        'uri': track['uri'],
                    })
            
            if results['next']:
                results = sp.next(results)
            else:
                break
        
        playlist_data = {
            'id': playlist['id'],
            'name': playlist['name'],
            'description': playlist.get('description', ''),
            'image': playlist['images'][0]['url'] if playlist['images'] else None,
            'owner': playlist['owner']['display_name'] or playlist['owner']['id'],
            'tracks_count': playlist['tracks']['total'],
            'public': playlist.get('public', False),
            'tracks': tracks_list,
        }
        
        return JsonResponse(playlist_data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def play_playlist(request):
    """Play a playlist."""
    playlist_id = request.GET.get('id', '')
    if not playlist_id:
        return JsonResponse({'error': 'Playlist ID required'}, status=400)
    
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        use_web_player = request.session.get('use_web_player', True)
        device_id = None
        
        if use_web_player:
            # For web player, we need the device_id from the frontend
            device_id = request.GET.get('device_id', None)
            if not device_id:
                return JsonResponse({'error': 'Web player device ID required'}, status=400)
        else:
            device_id = request.session.get('selected_device_id')
            if not device_id:
                return JsonResponse({'error': 'No device selected'}, status=400)
        
        # Start playback with the playlist
        sp.start_playback(device_id=device_id, context_uri=f'spotify:playlist:{playlist_id}')
        return JsonResponse({'status': 'playing', 'playlist_id': playlist_id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
