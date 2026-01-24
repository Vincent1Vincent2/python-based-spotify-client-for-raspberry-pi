import os
import stat
import subprocess
from configparser import ConfigParser
from pathlib import Path
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
        # Audio is NOT stored in config file - it's in /boot/firmware/config.txt and .env
        # Add audio section from .env for compatibility
        audio_output = os.getenv("I2S_AUDIO_OUTPUT") or os.getenv("AUDIO_OUTPUT", "analog")
        if not config.has_section("audio"):
            config.add_section("audio")
        config.set("audio", "output", audio_output)
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
    
    # Create audio section - ONLY from .env (not from config file)
    # I2S_AUDIO_OUTPUT takes precedence over AUDIO_OUTPUT (as per README)
    audio_output = os.getenv("I2S_AUDIO_OUTPUT") or os.getenv("AUDIO_OUTPUT", "analog")
    config.add_section("audio")
    config.set("audio", "output", audio_output)
    
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

def save_config(client_id, client_secret, redirect_uri, secret_key=None):
    """
    Save configuration to /etc/spotipi/spotipi.conf.
    Creates directory if needed and sets secure file permissions (600).
    
    Note: Audio configuration is NOT saved here - it's stored in /boot/firmware/config.txt
    and should be reflected in the .env file. Use update_env_audio_output() to update .env.
    
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
    
    # Note: Audio configuration is NOT saved to this config file
    # It's stored in /boot/firmware/config.txt and .env file
    
    # Create directory if it doesn't exist
    os.makedirs("/etc/spotipi", exist_ok=True)
    
    # Write config file
    with open(CONFIG_PATH, "w") as f:
        config.write(f)
    
    # Set secure permissions (owner read/write only)
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)

def update_env_audio_output(audio_output):
    """
    Update the .env file with the audio output setting.
    Preserves all other .env values.
    
    Args:
        audio_output: Audio output value (e.g., 'analog', 'x450', 'hifiberry-dac', etc.)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    # Find .env file path
    env_path = Path('/opt/spotipi/.env')
    if not env_path.exists():
        env_path = Path(__file__).resolve().parent.parent / '.env'
    
    try:
        # Read current .env (preserving all pre-configured values)
        env_lines = []
        audio_updated = False
        env_content_read = None
        
        if env_path.exists():
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    env_content_read = f.read()
            except PermissionError:
                # Try with sudo
                try:
                    result = subprocess.run(
                        ['sudo', 'cat', str(env_path)],
                        capture_output=True,
                        check=True,
                        text=True
                    )
                    env_content_read = result.stdout
                except (subprocess.CalledProcessError, FileNotFoundError):
                    return False, f"Could not read {env_path}"
            
            # Process each line, preserving all except AUDIO_OUTPUT/I2S_AUDIO_OUTPUT
            for line in env_content_read.splitlines(keepends=True):
                if line.strip().startswith('AUDIO_OUTPUT=') or line.strip().startswith('I2S_AUDIO_OUTPUT='):
                    if not audio_updated:
                        env_lines.append(f'AUDIO_OUTPUT={audio_output}\n')
                        audio_updated = True
                else:
                    env_lines.append(line)
        else:
            # Create new .env file
            env_lines = [f'AUDIO_OUTPUT={audio_output}\n']
            audio_updated = True
        
        if not audio_updated:
            env_lines.append(f'\nAUDIO_OUTPUT={audio_output}\n')
        
        # Write back using sudo if needed
        env_content = ''.join(env_lines)
        try:
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(env_content)
        except PermissionError:
            result = subprocess.run(
                ['sudo', 'tee', str(env_path)],
                input=env_content.encode('utf-8'),
                capture_output=True,
                check=False
            )
            if result.returncode != 0:
                return False, f"Could not write to {env_path}"
        
        return True, f"Updated .env with AUDIO_OUTPUT={audio_output}"
    except Exception as e:
        return False, f"Error updating .env: {str(e)}"

