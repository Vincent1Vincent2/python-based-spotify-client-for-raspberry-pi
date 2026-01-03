import os
import stat
from configparser import ConfigParser
from dotenv import load_dotenv

CONFIG_PATH = "/etc/spotipi/spotipi.conf"

# Load dev .env
load_dotenv()

def load_config():
    """
    Load configuration from /etc/spotipi/spotipi.conf (production) 
    or fallback to .env (development).
    """
    config = ConfigParser()
    
    # Production: read from /etc/spotipi/spotipi.conf
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
        return config
    
    # Development: fallback to .env
    # Create spotify section and add values
    config.add_section("spotify")
    config.set("spotify", "client_id", os.getenv("SPOTIFY_CLIENT_ID", ""))
    config.set("spotify", "client_secret", os.getenv("SPOTIFY_CLIENT_SECRET", ""))
    config.set("spotify", "redirect_uri", os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/callback"))
    
    # Create django section for SECRET_KEY
    config.add_section("django")
    config.set("django", "secret_key", os.getenv("SECRET_KEY", ""))
    
    # Create audio section
    config.add_section("audio")
    config.set("audio", "output", os.getenv("AUDIO_OUTPUT", "analog"))
    
    return config

def is_configured():
    """
    Check if Spotify credentials are configured.
    Returns True if all required credentials are present.
    """
    config = load_config()
    
    # Check if "spotify" section exists
    if not config.has_section("spotify"):
        return False
    
    # Get the spotify section
    spotify = config["spotify"]
    required_keys = ["client_id", "client_secret", "redirect_uri"]
    return all(spotify.get(k) for k in required_keys)

def generate_secret_key():
    """
    Generate a Django secret key.
    """
    try:
        from django.core.management.utils import get_random_secret_key
        return get_random_secret_key()
    except ImportError:
        import secrets
        return secrets.token_urlsafe(50)

def save_config(client_id, client_secret, redirect_uri, secret_key=None, audio_output="analog"):
    """
    Save configuration to /etc/spotipi/spotipi.conf.
    Creates directory if needed and sets secure file permissions (600).
    
    If secret_key is not provided, a new one will be generated automatically.
    
    Note: This requires appropriate permissions (root or sudo).
    For custom OS image, Django service should run with these permissions.
    """
    config = ConfigParser()
    config["spotify"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    
    # Generate SECRET_KEY if not provided
    if secret_key is None:
        secret_key = generate_secret_key()
    
    config["django"] = {
        "secret_key": secret_key,
    }
    
    config["audio"] = {
        "output": audio_output,
    }
    
    # Create directory if it doesn't exist
    os.makedirs("/etc/spotipi", exist_ok=True)
    
    # Write config file
    with open(CONFIG_PATH, "w") as f:
        config.write(f)
    
    # Set secure permissions (owner read/write only)
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)

