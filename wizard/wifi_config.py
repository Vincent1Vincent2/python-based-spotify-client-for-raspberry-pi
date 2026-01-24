"""
WiFi configuration module for Raspberry Pi.
Handles configuration of /etc/wpa_supplicant/wpa_supplicant.conf.
"""
import os
import stat
import re
import subprocess

WPA_SUPPLICANT_PATH = "/etc/wpa_supplicant/wpa_supplicant.conf"
WPA_SUPPLICANT_BACKUP = "/etc/wpa_supplicant/wpa_supplicant.conf.spotipi.backup"

def backup_wpa_supplicant():
    """Create a backup of wpa_supplicant.conf if it doesn't exist."""
    if os.path.exists(WPA_SUPPLICANT_PATH) and not os.path.exists(WPA_SUPPLICANT_BACKUP):
        try:
            import shutil
            shutil.copy2(WPA_SUPPLICANT_PATH, WPA_SUPPLICANT_BACKUP)
        except (PermissionError, IOError) as e:
            raise PermissionError(f"Cannot backup {WPA_SUPPLICANT_PATH}: {e}")

def read_wpa_supplicant():
    """Read /etc/wpa_supplicant/wpa_supplicant.conf content."""
    if not os.path.exists(WPA_SUPPLICANT_PATH):
        return None
    
    try:
        with open(WPA_SUPPLICANT_PATH, 'r') as f:
            return f.read()
    except (PermissionError, IOError) as e:
        raise PermissionError(f"Cannot read {WPA_SUPPLICANT_PATH}: {e}")

def write_wpa_supplicant(content):
    """Write content to /etc/wpa_supplicant/wpa_supplicant.conf."""
    try:
        # Ensure directory exists
        os.makedirs("/etc/wpa_supplicant", exist_ok=True)
        
        with open(WPA_SUPPLICANT_PATH, 'w') as f:
            f.write(content)
        
        # Set secure permissions (owner read/write only)
        os.chmod(WPA_SUPPLICANT_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except (PermissionError, IOError) as e:
        raise PermissionError(f"Cannot write to {WPA_SUPPLICANT_PATH}: {e}")

def escape_ssid(ssid):
    """Escape SSID for use in wpa_supplicant.conf."""
    # If SSID contains special characters or spaces, it needs to be quoted
    if ' ' in ssid or '\\' in ssid or '"' in ssid or '#' in ssid:
        # Escape quotes and backslashes
        escaped = ssid.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return ssid

def escape_password(password):
    """Escape password for use in wpa_supplicant.conf."""
    # Escape quotes and backslashes
    return password.replace('\\', '\\\\').replace('"', '\\"')

def configure_wifi(ssid, password):
    """
    Configure WiFi by modifying /etc/wpa_supplicant/wpa_supplicant.conf.
    
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
    
    # Skip configuration on non-Raspberry Pi systems (for development)
    if not os.path.exists("/boot/firmware/config.txt") and not os.path.exists("/etc/wpa_supplicant"):
        return True, f"WiFi configured: {ssid} (config files not found, skipping - development mode)"
    
    try:
        # Backup existing config
        existing_content = read_wpa_supplicant()
        if existing_content:
            backup_wpa_supplicant()
            
            # Check if this SSID already exists in the config
            # If it does, we could update it instead of adding new
            ssid_escaped = escape_ssid(ssid)
            if re.search(rf'^\s*ssid\s*=\s*{re.escape(ssid_escaped)}\s*$', existing_content, re.MULTILINE | re.IGNORECASE):
                # SSID exists, we could update it
                # For simplicity, we'll append a new network block
                # (wpa_supplicant uses the first matching network)
                pass
        
        # Build new network configuration
        ssid_escaped = escape_ssid(ssid)
        password_escaped = escape_password(password)
        
        # Create network block
        network_block = f"""
network={{
    ssid={ssid_escaped}
    psk="{password_escaped}"
}}
"""
        
        # If file exists, append to it, otherwise create new
        if existing_content:
            # Check if file has ctrl_interface (if not, it might be malformed)
            if 'ctrl_interface' in existing_content:
                # Append network block
                new_content = existing_content.rstrip() + network_block
            else:
                # Create new file with proper header
                new_content = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

{network_block.lstrip()}
"""
        else:
            # Create new file
            new_content = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

{network_block.lstrip()}
"""
        
        # Write configuration
        write_wpa_supplicant(new_content)
        
        # Reload wpa_supplicant configuration
        # Try to reload using wpa_cli if available
        try:
            subprocess.run(['wpa_cli', '-i', 'wlan0', 'reconfigure'], 
                         check=False, timeout=5, capture_output=True)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # wpa_cli not available or timed out, that's okay
            # The configuration will be applied on next reboot or manual reload
            pass
        
        return True, f"WiFi configured: {ssid}. Network will be connected on next reboot or reconnection."
    
    except PermissionError as e:
        return False, f"Permission denied: {e}. Ensure Django service has root/sudo permissions."
    except Exception as e:
        return False, f"Error configuring WiFi: {str(e)}"

def scan_wifi_networks():
    """
    Scan for available WiFi networks.
    Returns list of networks with SSID and signal strength.
    """
    networks = []
    
    try:
        # Try using iwlist first (more common on Raspberry Pi)
        result = subprocess.run(['iwlist', 'wlan0', 'scan'], 
                              capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            # Parse iwlist output
            current_ssid = None
            current_quality = None
            current_encryption = False
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                
                # Extract SSID
                if 'ESSID:' in line:
                    ssid_match = re.search(r'ESSID:"?([^"]+)"?', line)
                    if ssid_match:
                        current_ssid = ssid_match.group(1)
                        if current_ssid and current_ssid != '\\x00':
                            # Check if we've already added this network
                            if not any(n['ssid'] == current_ssid for n in networks):
                                networks.append({
                                    'ssid': current_ssid,
                                    'signal': current_quality or 0,
                                    'encrypted': current_encryption
                                })
                            current_ssid = None
                
                # Extract signal quality
                elif 'Quality=' in line or 'Signal level=' in line:
                    quality_match = re.search(r'Quality=(\d+)/(\d+)', line)
                    if quality_match:
                        current_quality = int((int(quality_match.group(1)) / int(quality_match.group(2))) * 100)
                    else:
                        level_match = re.search(r'Signal level=(-?\d+)', line)
                        if level_match:
                            level = int(level_match.group(1))
                            # Convert dBm to percentage (rough approximation)
                            current_quality = max(0, min(100, (level + 100) * 2))
                
                # Check for encryption
                elif 'Encryption key:' in line:
                    current_encryption = 'on' in line.lower()
            
            # Sort by signal strength (strongest first)
            networks.sort(key=lambda x: x['signal'], reverse=True)
            return networks
    
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    
    # Fallback: Try nmcli if available (NetworkManager)
    try:
        result = subprocess.run(['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list'], 
                              capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        ssid = parts[0].strip()
                        if ssid and ssid != '--':
                            signal = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0
                            encrypted = len(parts) > 2 and parts[2].strip() != ''
                            networks.append({
                                'ssid': ssid,
                                'signal': signal,
                                'encrypted': encrypted
                            })
            
            # Sort by signal strength (strongest first)
            networks.sort(key=lambda x: x['signal'], reverse=True)
            return networks
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    
    return networks

