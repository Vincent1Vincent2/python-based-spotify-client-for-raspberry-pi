"""
Consolidated configuration store for SpotiPi.

Replaces the previous split between /etc/spotipi/spotipi.conf, .env, and
ad-hoc file edits. Every setting the wizard or settings page can change
(Spotify credentials, audio output, wifi, hardware interface flags) lives
in ONE JSON file, read and written through this module only.

Environment selection:
    SPOTIPI_ENV=pi   -> real paths (/etc/spotipi/spotipi.json)
    SPOTIPI_ENV=dev  -> local ./devdata/spotipi.json (default)

The systemd service (install.sh) sets SPOTIPI_ENV=pi explicitly. Local
`manage.py runserver` runs in dev mode unless you export SPOTIPI_ENV=pi
yourself, so config bugs show up locally instead of being silently
skipped.

This module does NOT touch /boot/firmware/config.txt or
wpa_supplicant.conf directly — those remain the job of audio_config.py
and wifi_config.py, which will be updated separately to read the values
they need (dtoverlay choice, ssid/password) from this store instead of
from .env.
"""
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_env_mode():
    """Returns 'pi' or 'dev'. Defaults to 'dev' so local runs never
    silently touch real system paths unless explicitly told to."""
    mode = os.getenv("SPOTIPI_ENV", "dev").strip().lower()
    return "pi" if mode == "pi" else "dev"


def get_config_dir():
    if get_env_mode() == "pi":
        return Path("/etc/spotipi")
    return BASE_DIR / "devdata"


def get_config_path():
    return get_config_dir() / "spotipi.json"


# Defaults for every field this store manages. Used to fill in anything
# missing from an existing file (e.g. after upgrading) and to give the
# settings UI something to introspect.
DEFAULT_STORE = {
    "spotify": {
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "http://127.0.0.1:8000/callback",
    },
    "django": {
        "secret_key": "",
    },
    "audio": {
        "output": "analog",
    },
    "wifi": {
        # Last SSID we successfully wrote to wpa_supplicant.conf.
        # Password is never stored here in plaintext long-term - see note
        # in update_section().
        "last_ssid": "",
    },
    "hardware": {
        "i2c_arm_enabled": True,
        "i2s_enabled": True,
        "spi_enabled": True,
    },
}

# Metadata for the settings UI: which fields need a reboot/service
# restart to take effect once changed. Not enforced here, just exposed
# so the settings page can show an accurate warning per field instead of
# a blanket "reboot required" notice.
REQUIRES_RESTART = {
    "audio.output": "reboot",
    "hardware.i2c_arm_enabled": "reboot",
    "hardware.i2s_enabled": "reboot",
    "hardware.spi_enabled": "reboot",
    "wifi.last_ssid": "reboot",
    "spotify.client_id": "none",
    "spotify.client_secret": "none",
    "spotify.redirect_uri": "none",
    "django.secret_key": "service_restart",
}


def generate_secret_key():
    try:
        from django.core.management.utils import get_random_secret_key
        return get_random_secret_key()
    except ImportError:
        import secrets
        return secrets.token_urlsafe(50)


def _deep_merge_defaults(data):
    """Fill in any missing sections/keys from DEFAULT_STORE without
    overwriting anything already present."""
    merged = json.loads(json.dumps(DEFAULT_STORE))  # deep copy
    for section, values in data.items():
        if section not in merged:
            merged[section] = values
            continue
        if isinstance(values, dict) and isinstance(merged[section], dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def _read_raw(path):
    """Read file content, falling back to sudo cat on permission errors."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except PermissionError:
        result = subprocess.run(
            ["sudo", "cat", str(path)],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            raise PermissionError(f"Cannot read {path} (sudo cat failed): {result.stderr}")
        return result.stdout


def load_store():
    """
    Load the full config store as a dict, merged with defaults for any
    missing keys. Never raises for a missing/corrupt file - returns
    defaults instead so the app can still boot into the setup wizard.
    """
    path = get_config_path()

    if not path.exists():
        return json.loads(json.dumps(DEFAULT_STORE))

    try:
        raw = _read_raw(path)
        data = json.loads(raw)
    except (PermissionError, json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_STORE))

    if not isinstance(data, dict):
        return json.loads(json.dumps(DEFAULT_STORE))

    return _deep_merge_defaults(data)


def _write_raw(path, content):
    """
    Atomic write with a sudo fallback for permission errors. Writes to a
    temp file in the same directory, then renames over the target so a
    crash mid-write can never leave a half-written config file.
    """
    directory = path.parent

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        result = subprocess.run(
            ["sudo", "mkdir", "-p", str(directory)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return False, f"Cannot create {directory}: {result.stderr.decode(errors='ignore')}"

    fd, tmp_path = tempfile.mkstemp(dir=str(directory) if directory.exists() else None, prefix=".spotipi_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)

        try:
            os.replace(tmp_path, path)
        except PermissionError:
            result = subprocess.run(
                ["sudo", "mv", tmp_path, str(path)],
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                return False, f"Cannot write {path} (sudo mv failed): {result.stderr.decode(errors='ignore')}"

        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except PermissionError:
            subprocess.run(["sudo", "chmod", "600", str(path)], capture_output=True, check=False)

        return True, f"Wrote {path}"
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False, f"Error writing {path}: {e}"


def save_store(data):
    """
    Persist the full store dict to disk. Always writes ALL sections
    (this is a full save, not a merge) - callers that want to change one
    field should use update_section() instead.
    """
    path = get_config_path()
    content = json.dumps(data, indent=2, sort_keys=True)
    return _write_raw(path, content)


def update_section(section, updates):
    """
    Read-modify-write a single section (e.g. update_section("audio",
    {"output": "hifiberry-dac"})). Returns (success, message).

    Note on wifi passwords: this store is meant for settings that are
    safe to keep around for display/editing (like the last SSID used).
    Wifi passwords are written straight to wpa_supplicant.conf by
    wifi_config.py and are NOT persisted here, so this file never
    becomes a second copy of a plaintext network password.
    """
    current = load_store()
    if section not in current:
        current[section] = {}
    current[section].update(updates)
    return save_store(current)


def is_spotify_configured():
    store = load_store()
    spotify = store.get("spotify", {})
    required = ["client_id", "client_secret", "redirect_uri"]
    return all(spotify.get(k) for k in required)


def get_restart_requirement(section, key):
    """Returns 'none' | 'reboot' | 'service_restart' for a given field,
    defaulting to 'none' for anything not explicitly listed."""
    return REQUIRES_RESTART.get(f"{section}.{key}", "none")
