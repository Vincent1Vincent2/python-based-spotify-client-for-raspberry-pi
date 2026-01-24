from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from spotify_client.config import save_config, is_configured, update_env_audio_output
from wizard.audio_config import configure_audio_output, get_audio_options
from wizard.wifi_config import configure_wifi, scan_wifi_networks
import socket


def get_local_ip():
    """
    Get the local network IP address (not 127.0.0.1).
    Returns the IP address that other devices on the network can use to reach this machine.
    """
    try:
        # Connect to a remote address to determine the local IP
        # This doesn't actually send data, just determines which interface would be used
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            # Connect to a non-routable address (doesn't actually connect)
            s.connect(('10.254.254.254', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip
    except Exception:
        # Fallback to localhost if detection fails
        return '127.0.0.1'


def setup_view(request):
    """
    First-boot setup wizard for Spotify credentials.
    Works in both dev mode (.env) and production mode (/etc/spotipi/spotipi.conf).
    
    Note: For testing, wizard is always accessible. In production, middleware will handle redirects.
    """
    # Get the local IP address for the default redirect URI
    local_ip = get_local_ip()
    default_redirect_uri = f"http://{local_ip}:8000/callback"
    
    # Allow access to wizard even if configured (for testing/reconfiguration)
    # In production with middleware, unconfigured users will be redirected here automatically
    
    if request.method == "POST":
        client_id = request.POST.get("client_id", "").strip()
        client_secret = request.POST.get("client_secret", "").strip()
        redirect_uri = request.POST.get("redirect_uri", "").strip()
        audio_output = request.POST.get("audio_output_final", "analog").strip()
        
        # WiFi configuration (optional - can be skipped if using Ethernet)
        wifi_ssid = request.POST.get("wifi_ssid", "").strip()
        wifi_password = request.POST.get("wifi_password", "").strip()
        skip_wifi = request.POST.get("skip_wifi", "false") == "true"
        
        # Basic validation
        if not all([client_id, client_secret, redirect_uri]):
            messages.error(request, "Spotify credentials are required.")
            audio_options = get_audio_options()
            return render(request, "wizard/setup.html", {
                'default_redirect_uri': default_redirect_uri,
                'audio_options': audio_options
            })
        
        # Validate redirect URI format
        if not (redirect_uri.startswith("http://") or redirect_uri.startswith("https://")):
            messages.error(request, "Redirect URI must start with http:// or https://")
            audio_options = get_audio_options()
            return render(request, "wizard/setup.html", {
                'default_redirect_uri': default_redirect_uri,
                'audio_options': audio_options
            })
        
        try:
            # Configure WiFi if provided
            if not skip_wifi and wifi_ssid:
                wifi_success, wifi_message = configure_wifi(wifi_ssid, wifi_password)
                if not wifi_success:
                    messages.warning(request, f"WiFi configuration warning: {wifi_message}")
                else:
                    messages.info(request, wifi_message)
            
            # Configure audio output (modify /boot/firmware/config.txt)
            audio_success, audio_message = configure_audio_output(audio_output)
            if not audio_success:
                messages.warning(request, f"Audio configuration warning: {audio_message}")
            
            # Update .env file with audio output setting
            env_success, env_message = update_env_audio_output(audio_output)
            if not env_success:
                messages.warning(request, f".env update warning: {env_message}")
            
            # Save configuration (audio is NOT saved to config file, only to /boot/firmware/config.txt and .env)
            save_config(client_id, client_secret, redirect_uri)
            
            # Redirect to done page
            return redirect("/setup/done/")
        except PermissionError:
            messages.error(
                request, 
                "Permission denied. Cannot write to /etc/spotipi/. "
                "Ensure Django service has appropriate permissions."
            )
            audio_options = get_audio_options()
            return render(request, "wizard/setup.html", {
                'default_redirect_uri': default_redirect_uri,
                'audio_options': audio_options
            })
        except Exception as e:
            messages.error(request, f"Error saving configuration: {str(e)}")
            audio_options = get_audio_options()
            return render(request, "wizard/setup.html", {
                'default_redirect_uri': default_redirect_uri,
                'audio_options': audio_options
            })
    
    # GET request - show form with audio options
    audio_options = get_audio_options()
    return render(request, "wizard/setup.html", {
        'default_redirect_uri': default_redirect_uri,
        'audio_options': audio_options
    })

@csrf_exempt
def scan_wifi_view(request):
    """
    API endpoint to scan for WiFi networks.
    Returns JSON list of available networks.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        networks = scan_wifi_networks()
        return JsonResponse({'networks': networks}, safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def setup_done_view(request):
    """
    Setup completion page.
    """
    return render(request, "wizard/done.html")
