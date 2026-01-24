"""
Audio configuration module for Raspberry Pi I2S DAC setup.
Handles configuration of /boot/firmware/config.txt for various I2S DACs.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BOOT_CONFIG_PATH = "/boot/firmware/config.txt"
BOOT_CONFIG_BACKUP = "/boot/firmware/config.txt.spotipi.backup"

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
    "x450": {
        "name": "X450/X5500 DAC",
        "dtoverlay": "hifiberry-dac",
        "description": "X450/X5500 DAC+AMP Expansion Board"
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
    """Create a backup of /boot/firmware/config.txt if it doesn't exist."""
    if os.path.exists(BOOT_CONFIG_PATH) and not os.path.exists(BOOT_CONFIG_BACKUP):
        try:
            shutil.copy2(BOOT_CONFIG_PATH, BOOT_CONFIG_BACKUP)
        except (PermissionError, IOError):
            # Try with sudo
            try:
                result = subprocess.run(
                    ['sudo', 'cp', BOOT_CONFIG_PATH, BOOT_CONFIG_BACKUP],
                    capture_output=True,
                    check=True
                )
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                raise PermissionError(f"Cannot backup {BOOT_CONFIG_PATH}: {e}")

def read_config():
    """Read /boot/firmware/config.txt content."""
    if not os.path.exists(BOOT_CONFIG_PATH):
        raise FileNotFoundError(f"{BOOT_CONFIG_PATH} not found")
    
    try:
        with open(BOOT_CONFIG_PATH, 'r') as f:
            return f.read()
    except (PermissionError, IOError):
        # Try with sudo
        try:
            result = subprocess.run(
                ['sudo', 'cat', BOOT_CONFIG_PATH],
                capture_output=True,
                check=True,
                text=True
            )
            return result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise PermissionError(f"Cannot read {BOOT_CONFIG_PATH}: {e}")

def write_config(content):
    """Write content to /boot/firmware/config.txt."""
    try:
        with open(BOOT_CONFIG_PATH, 'w') as f:
            f.write(content)
    except (PermissionError, IOError):
        # Try with sudo using tee
        try:
            result = subprocess.run(
                ['sudo', 'tee', BOOT_CONFIG_PATH],
                input=content.encode('utf-8'),
                capture_output=True,
                check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
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

def _parse_bool_env(env_var, default=False):
    """Parse boolean environment variable (accepts true/false, on/off, 1/0)."""
    value = os.getenv(env_var, '').lower().strip()
    if value in ('true', 'on', '1', 'yes'):
        return True
    elif value in ('false', 'off', '0', 'no', ''):
        return False
    return default

def configure_audio_output(audio_option):
    """
    Configure Raspberry Pi audio output by modifying /boot/firmware/config.txt.
    Reads environment variables from .env file and applies them to config.txt.
    
    Environment variables (from .env):
    - I2C_ARM_ENABLED: Enable/disable i2c_arm (true/false, on/off)
    - I2S_ENABLED: Enable/disable i2s (true/false, on/off)
    - SPI_ENABLED: Enable/disable spi (true/false, on/off)
    - AUDIO_ENABLED: Enable/disable onboard audio (true/false, on/off)
    - DTOVERLAY: Device tree overlay for I2S DAC (e.g., hifiberry-dac)
    
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
        
        # Remove all I2S overlays first (we'll add the correct one later)
        lines = remove_i2s_overlays(lines)
        
        # Get the selected audio option configuration
        audio_config = AUDIO_OPTIONS[audio_option]
        dtoverlay_from_option = audio_config.get("dtoverlay")
        
        # Read environment variables (with fallback to audio_option if not set)
        i2c_enabled = _parse_bool_env("I2C_ARM_ENABLED", default=True)
        i2s_enabled = _parse_bool_env("I2S_ENABLED", default=True)
        spi_enabled = _parse_bool_env("SPI_ENABLED", default=True)
        
        # DTOVERLAY from env takes precedence, otherwise use audio_option
        dtoverlay_from_env = os.getenv("DTOVERLAY", "").strip()
        if dtoverlay_from_env:
            dtoverlay = dtoverlay_from_env
        else:
            dtoverlay = dtoverlay_from_option
        
        # AUDIO_ENABLED from env, but override logic: if I2S DAC is selected, disable onboard audio
        audio_enabled_env = _parse_bool_env("AUDIO_ENABLED", default=None)
        if dtoverlay:
            # I2S DAC selected: disable onboard audio (unless explicitly enabled in env)
            audio_enabled = audio_enabled_env if audio_enabled_env is not None else False
        elif audio_option == "analog":
            # Analog selected: enable onboard audio (unless explicitly disabled in env)
            audio_enabled = audio_enabled_env if audio_enabled_env is not None else True
        else:
            # HDMI or other: use env value or default to False
            audio_enabled = audio_enabled_env if audio_enabled_env is not None else False
        
        # Process hardware interface parameters (i2c_arm, i2s, spi)
        new_lines = []
        has_i2c = False
        has_i2s = False
        has_spi = False
        
        for line in lines:
            # Check for i2c_arm
            if re.match(r"#?\s*dtparam\s*=\s*i2c_arm\s*=", line.strip(), re.IGNORECASE):
                has_i2c = True
                if i2c_enabled:
                    # Enable: uncomment and set to on
                    new_lines.append("dtparam=i2c_arm=on")
                else:
                    # Disable: comment out
                    if not line.strip().startswith('#'):
                        new_lines.append('#' + line.lstrip())
                    else:
                        new_lines.append(line)
            # Check for i2s
            elif re.match(r"#?\s*dtparam\s*=\s*i2s\s*=", line.strip(), re.IGNORECASE):
                has_i2s = True
                if i2s_enabled:
                    # Enable: uncomment and set to on
                    new_lines.append("dtparam=i2s=on")
                else:
                    # Disable: comment out
                    if not line.strip().startswith('#'):
                        new_lines.append('#' + line.lstrip())
                    else:
                        new_lines.append(line)
            # Check for spi
            elif re.match(r"#?\s*dtparam\s*=\s*spi\s*=", line.strip(), re.IGNORECASE):
                has_spi = True
                if spi_enabled:
                    # Enable: uncomment and set to on
                    new_lines.append("dtparam=spi=on")
                else:
                    # Disable: comment out
                    if not line.strip().startswith('#'):
                        new_lines.append('#' + line.lstrip())
                    else:
                        new_lines.append(line)
            # Check for audio parameter
            elif re.match(r"#?\s*dtparam\s*=\s*audio\s*=", line.strip(), re.IGNORECASE):
                if audio_enabled:
                    # Enable: uncomment and set to on
                    new_lines.append("dtparam=audio=on")
                else:
                    # Disable: comment out
                    if not line.strip().startswith('#'):
                        new_lines.append('#' + line.lstrip())
                    else:
                        new_lines.append(line)
            else:
                new_lines.append(line)
        
        # Find insertion point for missing parameters (after comments, before other dtparam entries)
        insert_idx = len(new_lines)
        for i, line in enumerate(new_lines):
            if re.match(r"dtparam\s*=", line.strip(), re.IGNORECASE) and not line.strip().startswith('#'):
                insert_idx = i
                break
        
        # Add missing hardware interface parameters
        if not has_i2c and i2c_enabled:
            new_lines.insert(insert_idx, "dtparam=i2c_arm=on")
            insert_idx += 1
        if not has_i2s and i2s_enabled:
            new_lines.insert(insert_idx, "dtparam=i2s=on")
            insert_idx += 1
        if not has_spi and spi_enabled:
            new_lines.insert(insert_idx, "dtparam=spi=on")
            insert_idx += 1
        
        # Add audio parameter if needed
        audio_param_exists = any(re.match(r"#?\s*dtparam\s*=\s*audio\s*=", line.strip(), re.IGNORECASE) for line in new_lines)
        if not audio_param_exists:
            if audio_enabled:
                # Find insertion point after hardware interfaces
                insert_idx = len(new_lines)
                for i, line in enumerate(new_lines):
                    if re.match(r"dtparam\s*=\s*spi\s*=\s*on", line.strip(), re.IGNORECASE):
                        insert_idx = i + 1
                        break
                new_lines.insert(insert_idx, "dtparam=audio=on")
        
        lines = new_lines
        
        # Handle dtoverlay (I2S DAC)
        if dtoverlay:
            # Remove any existing dtoverlay entries first
            lines = [line for line in lines if not re.match(r"dtoverlay\s*=", line.strip(), re.IGNORECASE)]
            
            # Add dtoverlay at the END of the file (after removing trailing empty lines)
            while lines and lines[-1].strip() == '':
                lines.pop()
            lines.append(f"dtoverlay={dtoverlay}")
        else:
            # Remove any dtoverlay entries if no I2S DAC is selected
            lines = [line for line in lines if not re.match(r"dtoverlay\s*=", line.strip(), re.IGNORECASE)]
        
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

