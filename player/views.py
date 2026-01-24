from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json
import random
import requests
from .spotify_api import SpotifyAPI, get_spotify_api


SPOTIFY_SCOPE = 'user-modify-playback-state user-read-playback-state user-read-currently-playing user-read-playback-position streaming playlist-read-private playlist-read-collaborative user-library-read'


def get_spotify_client(request):
    """
    Get Spotify API client from session.
    DEPRECATED: Use get_spotify_api() instead.
    This is kept for backward compatibility during migration.
    """
    return get_spotify_api(request)


def index(request):
    """Main player interface."""
    sp = get_spotify_client(request)
    
    if not sp:
        return redirect('login')
    
    try:
        token_info = request.session.get('token_info', None)
        access_token = token_info.get('access_token') if token_info else None
        
        # Get available devices
        response = sp.get_devices()
        response.raise_for_status()
        devices_list = response.json()
        selected_device_id = request.session.get('selected_device_id', None)
        use_web_player = request.session.get('use_web_player', True)
        manual_selection = request.session.get('manual_device_selection', False)
        
        # Only auto-sync if user hasn't manually selected a device
        # This prevents auto-switching back after manual transfer
        if not manual_selection:
            # Check which device is actually playing
            try:
                response = sp.get_current_playback()
                if response.status_code == 204:
                    playback = None
                else:
                    response.raise_for_status()
                    playback = response.json()
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
            'client_id': settings.SPOTIFY_CLIENT_ID,
            'devices': devices_list.get('devices', []),
            'selected_device_id': selected_device_id,
            'use_web_player': use_web_player,
        }
    except Exception as e:
        context = {
            'error': str(e), 
            'access_token': None, 
            'client_id': settings.SPOTIFY_CLIENT_ID,
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
        # Use custom Spotify API client
        api = SpotifyAPI()
        auth_url = api.get_authorization_url(SPOTIFY_SCOPE)
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
    
    if not code:
        return render(request, 'player/error.html', {'error': 'No authorization code provided'})
    
    try:
        # Use custom Spotify API client
        api = SpotifyAPI()
        token_info = api.get_access_token(code)
        request.session['token_info'] = token_info
        request.session['use_web_player'] = True  # Default to web player
        
        return redirect('index')
    except Exception as e:
        return render(request, 'player/error.html', {'error': f'Authentication failed: {str(e)}'})


def token(request):
    """Get access token for Web Playback SDK."""
    api = get_spotify_api(request)
    if not api:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    # Token is already refreshed in get_spotify_api()
    token_info = request.session.get('token_info', None)
    if not token_info:
        return JsonResponse({'error': 'No token available'}, status=401)
    
    return JsonResponse({'access_token': token_info['access_token']})
    
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
        response = sp.search(q=query, type='track', limit=10)
        response.raise_for_status()
        results = response.json()
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
        response = sp.get_devices()
        response.raise_for_status()
        devices_list = response.json()
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


def current_playback(request):
    """
    Get current playback state including track or episode info.
    Uses Spotify API /v1/me/player endpoint per official documentation.
    """
    api = get_spotify_api(request)
    if not api:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        # Use the official Spotify API endpoint with additional_types to include episodes
        # According to Spotify API docs: additional_types can be "track,episode" to get both
        response = api.get_current_playback(additional_types='track,episode')
        
        # 204 No Content means no active device or nothing playing
        if response.status_code == 204:
            return JsonResponse({
                'is_playing': False,
                'track': None,
                'type': None,
                'device': None
            })
        
        # Handle other non-200 status codes
        if response.status_code != 200:
            error_msg = f'API error: {response.status_code}'
            try:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', error_msg)
            except:
                pass
            return JsonResponse({'error': error_msg}, status=response.status_code)
        
        playback = response.json()
        
        # Extract basic info from playback state
        item = playback.get('item')
        currently_playing_type = playback.get('currently_playing_type', 'track')
        is_playing = playback.get('is_playing', False)
        device = playback.get('device', {})
        progress_ms = playback.get('progress_ms', 0)
        
        # Process item if available
        if item:
            item_type = item.get('type', currently_playing_type)
            
            if item_type == 'episode':
                # Podcast episode - handle according to Spotify API structure
                show = item.get('show', {})
                images = item.get('images', [])
                
                episode_data = {
                    'id': item.get('id'),
                    'name': item.get('name', 'Unknown Episode'),
                    'show': show.get('name', 'Unknown Podcast') if show else 'Unknown Podcast',
                    'description': item.get('description', ''),
                    'image': images[0]['url'] if images and len(images) > 0 else None,
                    'duration_ms': item.get('duration_ms', 0),
                    'progress_ms': progress_ms,
                    'type': 'episode'
                }
                
                return JsonResponse({
                    'is_playing': is_playing,
                    'track': episode_data,
                    'type': 'episode',
                    'device': {
                        'id': device.get('id'),
                        'name': device.get('name'),
                        'type': device.get('type'),
                    }
                })
            else:
                # Track - handle according to Spotify API structure
                album = item.get('album', {})
                artists = item.get('artists', [])
                album_images = album.get('images', [])
                
                track_data = {
                    'id': item.get('id'),
                    'name': item.get('name', 'Unknown Track'),
                    'artists': [artist.get('name', 'Unknown Artist') for artist in artists],
                    'album': album.get('name', 'Unknown Album'),
                    'image': album_images[0]['url'] if album_images and len(album_images) > 0 else None,
                    'duration_ms': item.get('duration_ms', 0),
                    'progress_ms': progress_ms,
                    'type': 'track'
                }
                
                return JsonResponse({
                    'is_playing': is_playing,
                    'track': track_data,
                    'type': 'track',
                    'device': {
                        'id': device.get('id'),
                        'name': device.get('name'),
                        'type': device.get('type'),
                    }
                })
        
        # No item in response - device might be active but no track/episode loaded
        # This can happen when playback is paused or between tracks
        return JsonResponse({
            'is_playing': is_playing,
            'track': None,
            'type': None,
            'device': {
                'id': device.get('id'),
                'name': device.get('name'),
                'type': device.get('type'),
            } if device else None
        })
        
    except requests.exceptions.RequestException as e:
        return JsonResponse({'error': f'Request failed: {str(e)}'}, status=500)
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
        response = sp.get_devices()
        response.raise_for_status()
        devices_list = response.json()
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
            response = sp.get_devices()
            response.raise_for_status()
            devices_list = response.json()
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
    """Get user's playlists with pagination."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        offset = int(request.GET.get('offset', 0))
        limit = int(request.GET.get('limit', 50))
        
        playlists_list = []
        response = sp.get_user_playlists(limit=limit, offset=offset)
        response.raise_for_status()
        results = response.json()
        
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
        
        # Check if there are more playlists
        has_more = results['next'] is not None
        
        return JsonResponse({
            'playlists': playlists_list,
            'has_more': has_more,
            'offset': offset,
            'total': results.get('total', 0)
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def albums(request):
    """Get user's saved albums with pagination."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        offset = int(request.GET.get('offset', 0))
        limit = int(request.GET.get('limit', 50))
        
        albums_list = []
        response = sp.get_user_saved_albums(limit=limit, offset=offset)
        response.raise_for_status()
        results = response.json()
        
        for item in results['items']:
            album = item['album']
            albums_list.append({
                'id': album['id'],
                'name': album['name'],
                'artists': [artist['name'] for artist in album['artists']],
                'image': album['images'][0]['url'] if album['images'] else None,
                'release_date': album.get('release_date', ''),
                'total_tracks': album.get('total_tracks', 0),
            })
        
        # Check if there are more albums
        has_more = results['next'] is not None
        
        return JsonResponse({
            'albums': albums_list,
            'has_more': has_more,
            'offset': offset,
            'total': results.get('total', 0)
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def saved_tracks(request):
    """Get user's saved tracks (liked songs) with pagination."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        offset = int(request.GET.get('offset', 0))
        limit = int(request.GET.get('limit', 50))
        
        tracks_list = []
        response = sp.get_user_saved_tracks(limit=limit, offset=offset)
        response.raise_for_status()
        results = response.json()
        
        for item in results['items']:
            track = item['track']
            tracks_list.append({
                'id': track['id'],
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']],
                'album': track['album']['name'],
                'image': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'duration_ms': track.get('duration_ms', 0),
                'uri': track['uri'],
                'added_at': item.get('added_at', ''),
            })
        
        # Check if there are more tracks
        has_more = results['next'] is not None
        
        return JsonResponse({
            'tracks': tracks_list,
            'has_more': has_more,
            'offset': offset,
            'total': results.get('total', 0)
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def settings_view(request):
    """Settings page for audio configuration."""
    from spotify_client.config import load_config
    from wizard.audio_config import get_audio_options
    
    sp = get_spotify_client(request)
    if not sp:
        return redirect('login')
    
    # Get current audio output
    config = load_config()
    current_audio_output = config.get('audio', 'output', fallback='analog')
    
    # Get available audio options
    audio_options = get_audio_options()
    
    return render(request, 'player/settings.html', {
        'audio_options': audio_options,
        'current_audio_output': current_audio_output
    })


@require_http_methods(["POST"])
@csrf_exempt
def update_audio_settings(request):
    """Update audio output settings."""
    import json
    from wizard.audio_config import configure_audio_output
    from spotify_client.config import update_env_audio_output
    
    try:
        data = json.loads(request.body)
        audio_output = data.get('audio_output')
        
        if not audio_output:
            return JsonResponse({'success': False, 'error': 'No audio output specified'}, status=400)
        
        # Configure /boot/firmware/config.txt
        success, message = configure_audio_output(audio_output)
        
        if not success:
            return JsonResponse({'success': False, 'error': message}, status=400)
        
        # Update .env file to reflect the audio configuration
        env_success, env_message = update_env_audio_output(audio_output)
        
        if not env_success:
            return JsonResponse({'success': False, 'error': f'Error updating .env: {env_message}'}, status=500)
        
        return JsonResponse({
            'success': True,
            'message': message
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def reboot_system(request):
    """Reboot the Raspberry Pi system."""
    import subprocess
    try:
        # Reboot the system
        result = subprocess.run(
            ['sudo', 'reboot'],
            capture_output=True,
            check=False,
            timeout=5
        )
        if result.returncode == 0:
            return JsonResponse({'success': True, 'message': 'System rebooting...'})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to reboot system'}, status=500)
    except subprocess.TimeoutExpired:
        # Reboot command doesn't return, so timeout is expected
        return JsonResponse({'success': True, 'message': 'System rebooting...'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def discover(request):
    """Get random discover content - playlists, albums, and tracks."""
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        discover_data = {
            'playlists': [],
            'albums': [],
            'tracks': []
        }
        
        # Get random categories for playlists
        try:
            response = sp.get_categories(limit=50)
            response.raise_for_status()
            categories = response.json()
            if categories and categories.get('categories', {}).get('items'):
                category_items = categories['categories']['items']
                random_categories = random.sample(category_items, min(3, len(category_items)))
                
                for category in random_categories:
                    try:
                        response = sp.get_category_playlists(category_id=category['id'], limit=10)
                        response.raise_for_status()
                        playlists = response.json()
                        if playlists and playlists.get('playlists', {}).get('items'):
                            for playlist in playlists['playlists']['items'][:3]:  # Take 3 from each category
                                discover_data['playlists'].append({
                                    'id': playlist['id'],
                                    'name': playlist['name'],
                                    'description': playlist.get('description', ''),
                                    'image': playlist['images'][0]['url'] if playlist['images'] else None,
                                    'tracks_count': playlist['tracks']['total'],
                                    'owner': playlist['owner']['display_name'] or playlist['owner']['id'],
                                    'type': 'playlist'
                                })
                    except:
                        continue
        except:
            pass
        
        # Get featured playlists
        try:
            response = sp.get_featured_playlists(limit=20)
            response.raise_for_status()
            featured = response.json()
            if featured and featured.get('playlists', {}).get('items'):
                for playlist in random.sample(featured['playlists']['items'], min(5, len(featured['playlists']['items']))):
                    discover_data['playlists'].append({
                        'id': playlist['id'],
                        'name': playlist['name'],
                        'description': playlist.get('description', ''),
                        'image': playlist['images'][0]['url'] if playlist['images'] else None,
                        'tracks_count': playlist['tracks']['total'],
                        'owner': playlist['owner']['display_name'] or playlist['owner']['id'],
                        'type': 'playlist'
                    })
        except:
            pass
        
        # Get new releases (random albums)
        try:
            response = sp.get_new_releases(limit=50)
            response.raise_for_status()
            new_releases = response.json()
            if new_releases and new_releases.get('albums', {}).get('items'):
                random_albums = random.sample(new_releases['albums']['items'], min(10, len(new_releases['albums']['items'])))
                for album in random_albums:
                    discover_data['albums'].append({
                        'id': album['id'],
                        'name': album['name'],
                        'artists': [artist['name'] for artist in album['artists']],
                        'image': album['images'][0]['url'] if album['images'] else None,
                        'release_date': album.get('release_date', ''),
                        'total_tracks': album.get('total_tracks', 0),
                        'type': 'album'
                    })
        except:
            pass
        
        # Get random recommendations using random genres
        try:
            response = sp.get_recommendation_genre_seeds()
            response.raise_for_status()
            available_genres = response.json()
            if available_genres and available_genres.get('genres'):
                genres_list = available_genres['genres']
                random_genres = random.sample(genres_list, min(5, len(genres_list)))
                
                # Get recommendations for each genre
                for genre in random_genres:
                    try:
                        response = sp.get_recommendations(seed_genres=[genre], limit=10)
                        response.raise_for_status()
                        recommendations = response.json()
                        if recommendations and recommendations.get('tracks'):
                            for track in recommendations['tracks'][:3]:  # Take 3 from each genre
                                discover_data['tracks'].append({
                                    'id': track['id'],
                                    'name': track['name'],
                                    'artists': [artist['name'] for artist in track['artists']],
                                    'album': track['album']['name'],
                                    'image': track['album']['images'][0]['url'] if track['album']['images'] else None,
                                    'duration_ms': track.get('duration_ms', 0),
                                    'uri': track['uri'],
                                    'type': 'track',
                                    'preview_url': track.get('preview_url')
                                })
                    except:
                        continue
        except:
            pass
        
        # Shuffle everything for maximum randomness
        random.shuffle(discover_data['playlists'])
        random.shuffle(discover_data['albums'])
        random.shuffle(discover_data['tracks'])
        
        # Limit each type to reasonable amounts
        discover_data['playlists'] = discover_data['playlists'][:15]
        discover_data['albums'] = discover_data['albums'][:15]
        discover_data['tracks'] = discover_data['tracks'][:20]
        
        return JsonResponse(discover_data)
    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=400)


def album_detail(request):
    """Get detailed information about a specific album including tracks."""
    album_id = request.GET.get('id', '')
    if not album_id:
        return JsonResponse({'error': 'Album ID required'}, status=400)
    
    sp = get_spotify_client(request)
    if not sp:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    try:
        # Get album details
        response = sp.get_album(album_id)
        response.raise_for_status()
        album = response.json()
        
        # Get all tracks in the album
        tracks_list = []
        results = album['tracks']
        offset = 0
        limit = 50
        
        while True:
            for track in results['items']:
                if track:
                    # Get full track details for images
                    track_image = album['images'][0]['url'] if album['images'] else None
                    tracks_list.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artists': [artist['name'] for artist in track['artists']],
                        'album': album['name'],
                        'image': track_image,
                        'duration_ms': track.get('duration_ms', 0),
                        'uri': track['uri'],
                    })
            
            if results['next']:
                # Parse next URL to get offset
                offset += limit
                response = sp.get(f'albums/{album_id}/tracks', params={'limit': limit, 'offset': offset})
                response.raise_for_status()
                results = response.json()
            else:
                break
        
        album_data = {
            'id': album['id'],
            'name': album['name'],
            'artists': [artist['name'] for artist in album['artists']],
            'image': album['images'][0]['url'] if album['images'] else None,
            'release_date': album.get('release_date', ''),
            'total_tracks': album.get('total_tracks', 0),
            'tracks': tracks_list,
        }
        
        return JsonResponse(album_data)
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
        response = sp.get_playlist(playlist_id)
        response.raise_for_status()
        playlist = response.json()
        
        # Get all tracks in the playlist
        tracks_list = []
        offset = 0
        limit = 100
        
        response = sp.get_playlist_tracks(playlist_id, limit=limit, offset=offset)
        response.raise_for_status()
        results = response.json()
        
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
                offset += limit
                response = sp.get_playlist_tracks(playlist_id, limit=limit, offset=offset)
                response.raise_for_status()
                results = response.json()
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


@csrf_exempt
@require_http_methods(["POST"])
def play_album(request):
    """Play an album."""
    album_id = request.GET.get('id', '')
    if not album_id:
        return JsonResponse({'error': 'Album ID required'}, status=400)
    
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
        
        # Start playback with the album
        sp.start_playback(device_id=device_id, context_uri=f'spotify:album:{album_id}')
        return JsonResponse({'status': 'playing', 'album_id': album_id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
