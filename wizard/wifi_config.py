"""
WiFi configuration module for Raspberry Pi.
Handles configuration of wpa_supplicant.conf (real path on the Pi, a
local mock file in dev mode).

Passwords are written straight to wpa_supplicant.conf and are never
persisted in config_store's JSON file - only the last SSID used is
kept there, for display in the settings page. See the note in
config_store.update_section().
"""
import os
import re
import shutil
import stat
import subprocess

from spotify_client import config_store

# A handful of fake networks so the settings/wizard UI's wifi-scan flow
# can be built and tested locally without real wifi hardware. Only used
# as a last resort - see scan_wifi_networks().
DEV_MOCK_NETWORKS = [
    {"ssid": "SpotiPi-Dev-Network", "signal": 88, "encrypted": True},
    {"ssid": "Guest WiFi", "signal": 54, "encrypted": False},
    {"ssid": "Neighbor_5G", "signal": 32, "encrypted": True},
]


def get_wpa_supplicant_path():
    if config_store.get_env_mode() == "pi":
        return "/etc/wpa_supplicant/wpa_supplicant.conf"
    return str(config_store.get_config_dir() / "mock_wpa_supplicant.conf")


def get_wpa_supplicant_backup_path():
    return get_wpa_supplicant_path() + ".spotipi.backup"


def backup_wpa_supplicant():
    """Create a backup of wpa_supplicant.conf if one doesn't exist yet."""
    path = get_wpa_supplicant_path()
    backup_path = get_wpa_supplicant_backup_path()

    if os.path.exists(path) and not os.path.exists(backup_path):
        try:
            shutil.copy2(path, backup_path)
        except (PermissionError, IOError) as e:
            raise PermissionError(f"Cannot backup {path}: {e}")


def read_wpa_supplicant():
    """Read wpa_supplicant.conf content, or None if it doesn't exist yet."""
    path = get_wpa_supplicant_path()

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r") as f:
            return f.read()
    except (PermissionError, IOError) as e:
        raise PermissionError(f"Cannot read {path}: {e}")


def write_wpa_supplicant(content):
    """Write content to wpa_supplicant.conf (real path or dev mock)."""
    path = get_wpa_supplicant_path()

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except (PermissionError, IOError) as e:
        raise PermissionError(f"Cannot write to {path}: {e}")


def escape_ssid(ssid):
    """Escape SSID for use in wpa_supplicant.conf."""
    if " " in ssid or "\\" in ssid or '"' in ssid or "#" in ssid:
        escaped = ssid.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return ssid


def escape_password(password):
    """Escape password for use in wpa_supplicant.conf."""
    return password.replace("\\", "\\\\").replace('"', '\\"')


def configure_wifi(ssid, password):
    """
    Configure WiFi by writing a network block into wpa_supplicant.conf.

    Args:
        ssid: WiFi network name (SSID)
        password: WiFi password (PSK)

    Returns:
        tuple: (success: bool, message: str)
    """
    if not ssid or not ssid.strip():
        return False, "SSID cannot be empty"

    ssid = ssid.strip()
    password = password.strip() if password else ""

    try:
        existing_content = read_wpa_supplicant()
        if existing_content:
            backup_wpa_supplicant()

        ssid_escaped = escape_ssid(ssid)
        password_escaped = escape_password(password)

        network_block = f"""
network={{
    ssid={ssid_escaped}
    psk="{password_escaped}"
}}
"""

        if existing_content and "ctrl_interface" in existing_content:
            new_content = existing_content.rstrip() + network_block
        else:
            new_content = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

{network_block.lstrip()}
"""

        write_wpa_supplicant(new_content)

        # Only meaningful on the Pi - reload if wpa_cli is present.
        try:
            subprocess.run(
                ["wpa_cli", "-i", "wlan0", "reconfigure"],
                check=False, timeout=5, capture_output=True,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Remember the SSID (never the password) for the settings page.
        config_store.update_section("wifi", {"last_ssid": ssid})

        suffix = "" if config_store.get_env_mode() == "pi" else " (dev mode: written to mock wpa_supplicant file)"
        return True, f"WiFi configured: {ssid}. Network will be connected on next reboot or reconnection.{suffix}"

    except PermissionError as e:
        return False, f"Permission denied: {e}. Ensure the SpotiPi service has root/sudo permissions."
    except Exception as e:
        return False, f"Error configuring WiFi: {str(e)}"


def _scan_with_iwlist():
    result = subprocess.run(
        ["iwlist", "wlan0", "scan"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return None

    networks = []
    current_quality = None
    current_encryption = False

    for line in result.stdout.split("\n"):
        line = line.strip()

        if "ESSID:" in line:
            ssid_match = re.search(r'ESSID:"?([^"]+)"?', line)
            if ssid_match:
                current_ssid = ssid_match.group(1)
                if current_ssid and current_ssid != "\\x00":
                    if not any(n["ssid"] == current_ssid for n in networks):
                        networks.append({
                            "ssid": current_ssid,
                            "signal": current_quality or 0,
                            "encrypted": current_encryption,
                        })
        elif "Quality=" in line or "Signal level=" in line:
            quality_match = re.search(r"Quality=(\d+)/(\d+)", line)
            if quality_match:
                current_quality = int((int(quality_match.group(1)) / int(quality_match.group(2))) * 100)
            else:
                level_match = re.search(r"Signal level=(-?\d+)", line)
                if level_match:
                    level = int(level_match.group(1))
                    current_quality = max(0, min(100, (level + 100) * 2))
        elif "Encryption key:" in line:
            current_encryption = "on" in line.lower()

    networks.sort(key=lambda x: x["signal"], reverse=True)
    return networks


def _scan_with_nmcli():
    result = subprocess.run(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return None

    networks = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 2:
            continue
        ssid = parts[0].strip()
        if not ssid or ssid == "--":
            continue
        signal = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
        encrypted = len(parts) > 2 and parts[2].strip() != ""
        networks.append({"ssid": ssid, "signal": signal, "encrypted": encrypted})

    networks.sort(key=lambda x: x["signal"], reverse=True)
    return networks


def scan_wifi_networks():
    """
    Scan for available WiFi networks. Tries iwlist, then nmcli. If
    neither is available (e.g. most dev machines without those tools),
    falls back to a small fixed mock list in dev mode only, so the
    scan-and-select UI flow can still be exercised locally - production
    (pi mode) returns an empty list instead, same as before.
    """
    for scanner in (_scan_with_iwlist, _scan_with_nmcli):
        try:
            result = scanner()
            if result is not None:
                return result
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            continue

    if config_store.get_env_mode() == "dev":
        return DEV_MOCK_NETWORKS

    return []