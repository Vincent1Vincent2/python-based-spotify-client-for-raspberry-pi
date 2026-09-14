"""
Backward-compatible wrapper around config_store.

Kept as spotify_client/config.py because settings.py, player/views.py,
and wizard/views.py all import load_config / is_configured / save_config
/ update_env_audio_output from here. The function names and the
ConfigParser-shaped return value of load_config() are preserved so
those call sites don't need to change in this pass - only the storage
underneath does (single JSON store via config_store, not .env/.conf).

Note: load_config() returning a ConfigParser is a transitional shim.
A later pass can simplify settings.py / views.py to use config_store's
dict API directly and this wrapper can shrink or disappear.
"""
from configparser import ConfigParser

from spotify_client import config_store


def load_config():
    """
    Returns a ConfigParser populated from the consolidated store, so
    existing call sites using config.get(section, key, fallback=...) /
    config.has_section(...) keep working unchanged.
    """
    store = config_store.load_store()
    parser = ConfigParser()

    for section, values in store.items():
        if not isinstance(values, dict):
            continue
        parser.add_section(section)
        for key, value in values.items():
            # ConfigParser values must be strings.
            if isinstance(value, bool):
                value = "true" if value else "false"
            parser.set(section, key, str(value))

    return parser


def is_configured():
    """Check if Spotify credentials are configured."""
    return config_store.is_spotify_configured()


def generate_secret_key():
    return config_store.generate_secret_key()


def save_config(client_id, client_secret, redirect_uri, secret_key=None):
    """
    Save Spotify credentials (and the Django secret key) to the
    consolidated store.

    Unlike the old implementation, this does NOT generate a new secret
    key on every save when one already exists - regenerating it on
    every wizard save would silently invalidate every logged-in
    session each time settings were touched. A secret key is only
    generated the first time (or if explicitly passed in).
    """
    store = config_store.load_store()

    if secret_key is None:
        existing = store.get("django", {}).get("secret_key", "")
        secret_key = existing if existing else generate_secret_key()

    store["spotify"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    store["django"] = {
        "secret_key": secret_key,
    }

    return config_store.save_store(store)


def update_env_audio_output(audio_output):
    """
    Update the stored audio output setting.

    Kept under its old name (previously wrote to .env) since
    wizard/views.py and player/views.py call it directly; now it just
    writes into the "audio" section of the consolidated store instead.

    Returns:
        tuple: (success: bool, message: str)
    """
    success, message = config_store.update_section("audio", {"output": audio_output})
    if success:
        return True, f"Saved audio output setting: {audio_output}"
    return False, message