"""
Audio configuration module for Raspberry Pi I2S DAC setup.
Handles configuration of /boot/config.txt for various I2S DACs.
"""
import os
import re
import shutil
from pathlib import Path

BOOT_CONFIG_PATH = "/boot/config.txt"
BOOT_CONFIG_BACKUP = "/boot/config.txt.spotipi.backup"

# Mapping of audio output options to their dtoverlay configurations
AUDIO_OPTIONS = {
    "analog": {
        "name": "3.5mm Analog Jack",
        "dtoverlay": None,  # Default/remove I2S overlays
        "description": "Built-in 3.5mm audio jack"
    },
    "hifiberry-dac": {
        "name": "HiFiBerry DAC+",
        "dtoverlay": "hifiberry-dac",
        "description": "HiFiBerry DAC+ basic model"
    },
    "hifiberry-dacplus": {
        "name": "HiFiBerry DAC+ Light",
        "dtoverlay": "hifiberry-dacplus",
        "description": "HiFiBerry DAC+ Light"
    },
    "hifiberry-dacplusadc": {
        "name": "HiFiBerry DAC+ Pro",
        "dtoverlay": "hifiberry-dacplusadc",
        "description": "HiFiBerry DAC+ Pro (with ADC)"
    },
    "iqaudio-dacplus": {
        "name": "IQaudio DAC+",
        "dtoverlay": "iqaudio-dacplus",
        "description": "IQaudio DAC+"
    },
    "justboom-dac": {
        "name": "JustBoom DAC",
        "dtoverlay": "justboom-dac",
        "description": "JustBoom DAC"
    },
    "allo-boss-dac": {
        "name": "Allo Boss DAC",
        "dtoverlay": "allo-boss-dac-pcm512x-audio",
        "description": "Allo Boss DAC"
    },
    "allo-boss2-dac": {
        "name": "Allo Boss2 DAC",
        "dtoverlay": "allo-boss2-dac-pcm512x-audio",
        "description": "Allo Boss2 DAC"
    },
    "hdmi": {
        "name": "HDMI Audio",
        "dtoverlay": None,
        "description": "HDMI audio output (disable analog)"
    }
}

# Common I2S overlay patterns to remove
I2S_OVERLAY_PATTERNS = [
    r"dtoverlay\s*=\s*hifiberry-.*",
    r"dtoverlay\s*=\s*iqaudio-.*",
    r"dtoverlay\s*=\s*justboom-.*",
    r"dtoverlay\s*=\s*allo-.*",
    r"dtoverlay\s*=\s*i2s-mmap",
]

def backup_config():
    """Create a backup of /boot/config.txt if it doesn't exist."""
    if os.path.exists(BOOT_CONFIG_PATH) and not os.path.exists(BOOT_CONFIG_BACKUP):
        try:
            shutil.copy2(BOOT_CONFIG_PATH, BOOT_CONFIG_BACKUP)
        except (PermissionError, IOError) as e:
            raise PermissionError(f"Cannot backup {BOOT_CONFIG_PATH}: {e}")

def read_config():
    """Read /boot/config.txt content."""
    if not os.path.exists(BOOT_CONFIG_PATH):
        raise FileNotFoundError(f"{BOOT_CONFIG_PATH} not found")
    
    try:
        with open(BOOT_CONFIG_PATH, 'r') as f:
            return f.read()
    except (PermissionError, IOError) as e:
        raise PermissionError(f"Cannot read {BOOT_CONFIG_PATH}: {e}")

def write_config(content):
    """Write content to /boot/config.txt."""
    try:
        with open(BOOT_CONFIG_PATH, 'w') as f:
            f.write(content)
    except (PermissionError, IOError) as e:
        raise PermissionError(f"Cannot write to {BOOT_CONFIG_PATH}: {e}")

def remove_i2s_overlays(lines):
    """Remove all I2S-related dtoverlay entries from config lines."""
    new_lines = []
    for line in lines:
        # Check if line matches any I2S overlay pattern
        is_i2s_overlay = False
        for pattern in I2S_OVERLAY_PATTERNS:
            if re.match(pattern, line.strip(), re.IGNORECASE):
                is_i2s_overlay = True
                break
        
        if not is_i2s_overlay:
            new_lines.append(line)
    
    return new_lines

def configure_audio_output(audio_option):
    """
    Configure Raspberry Pi audio output by modifying /boot/config.txt.
    
    Args:
        audio_option: Key from AUDIO_OPTIONS (e.g., 'hifiberry-dac', 'analog', etc.)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    if audio_option not in AUDIO_OPTIONS:
        return False, f"Unknown audio option: {audio_option}"
    
    # Skip configuration on non-Raspberry Pi systems (for development)
    if not os.path.exists(BOOT_CONFIG_PATH):
        return True, f"Audio option '{AUDIO_OPTIONS[audio_option]['name']}' selected (config.txt not found, skipping)"
    
    try:
        # Backup config file
        backup_config()
        
        # Read current config
        config_content = read_config()
        lines = config_content.split('\n')
        
        # Remove all I2S overlays
        lines = remove_i2s_overlays(lines)
        
        # Get the selected audio option configuration
        audio_config = AUDIO_OPTIONS[audio_option]
        dtoverlay = audio_config.get("dtoverlay")
        
        # Add new dtoverlay if needed
        if dtoverlay:
            # Find where to insert (after [all] section or at end)
            insert_index = len(lines)
            for i, line in enumerate(lines):
                if line.strip().startswith('[all]') or line.strip().startswith('[pi'):
                    # Look for the next blank line or end of section
                    for j in range(i + 1, len(lines)):
                        if lines[j].strip() == '' or lines[j].strip().startswith('['):
                            insert_index = j
                            break
                    if insert_index == len(lines):
                        insert_index = i + 1
                    break
            
            # Insert dtoverlay line
            lines.insert(insert_index, f"dtoverlay={dtoverlay}")
        
        # Handle HDMI audio (disable analog)
        if audio_option == "hdmi":
            # Remove dtparam=audio=on if present, or add dtparam=audio=off
            lines = [line for line in lines if not re.match(r"dtparam\s*=\s*audio\s*=", line.strip(), re.IGNORECASE)]
            # HDMI audio is usually default, but we can be explicit
            # Actually, for HDMI, we don't need to add anything special
        
        # Write modified config
        new_content = '\n'.join(lines)
        write_config(new_content)
        
        return True, f"Audio output configured: {audio_config['name']}. Reboot required for changes to take effect."
    
    except PermissionError as e:
        return False, f"Permission denied: {e}. Ensure Django service has root/sudo permissions."
    except Exception as e:
        return False, f"Error configuring audio: {str(e)}"

def get_audio_options():
    """Get list of available audio options for display."""
    return [
        {
            "value": key,
            "name": value["name"],
            "description": value["description"]
        }
        for key, value in AUDIO_OPTIONS.items()
    ]

