"""
Audio configuration module for Raspberry Pi I2S DAC setup.
Handles configuration of /boot/firmware/config.txt (or its dev-mode
mock equivalent) for various I2S DACs.
"""
import os
import re
import shutil
import subprocess

from spotify_client import config_store

AUDIO_OPTIONS = {
    "analog": {
        "name": "3.5mm Analog Jack",
        "dtoverlay": None,
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

# Common I2S overlay patterns to remove before adding the new selection
I2S_OVERLAY_PATTERNS = [
    r"dtoverlay\s*=\s*hifiberry-.*",
    r"dtoverlay\s*=\s*iqaudio-.*",
    r"dtoverlay\s*=\s*justboom-.*",
    r"dtoverlay\s*=\s*allo-.*",
    r"dtoverlay\s*=\s*i2s-mmap",
]


def get_boot_config_path():
    """
    Real path on the Pi, or a local mock file in dev mode. Using a real
    (if fake) file in dev mode means the line-rewriting logic below
    actually runs and can be inspected/tested locally, instead of the
    old behavior of silently no-op'ing whenever config.txt wasn't
    found.
    """
    if config_store.get_env_mode() == "pi":
        return "/boot/firmware/config.txt"
    return str(config_store.get_config_dir() / "mock_boot_config.txt")


def get_boot_config_backup_path():
    return get_boot_config_path() + ".spotipi.backup"


def backup_config():
    """Create a one-time backup of the boot config before we ever touch it."""
    boot_path = get_boot_config_path()
    backup_path = get_boot_config_backup_path()

    if os.path.exists(boot_path) and not os.path.exists(backup_path):
        try:
            shutil.copy2(boot_path, backup_path)
        except (PermissionError, IOError):
            result = subprocess.run(
                ["sudo", "cp", boot_path, backup_path],
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise PermissionError(f"Cannot backup {boot_path}: {result.stderr.decode(errors='ignore')}")


def read_config():
    """Read the boot config file content. In dev mode, a missing mock
    file is treated as an empty starting point rather than an error."""
    boot_path = get_boot_config_path()

    if not os.path.exists(boot_path):
        if config_store.get_env_mode() == "dev":
            return ""
        raise FileNotFoundError(f"{boot_path} not found")

    try:
        with open(boot_path, "r") as f:
            return f.read()
    except (PermissionError, IOError):
        result = subprocess.run(
            ["sudo", "cat", boot_path],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            raise PermissionError(f"Cannot read {boot_path}: {result.stderr}")
        return result.stdout


def write_config(content):
    """Write content to the boot config file (real path or dev mock)."""
    boot_path = get_boot_config_path()

    try:
        os.makedirs(os.path.dirname(boot_path), exist_ok=True)
    except (PermissionError, FileNotFoundError):
        pass

    try:
        with open(boot_path, "w") as f:
            f.write(content)
    except (PermissionError, IOError):
        result = subprocess.run(
            ["sudo", "tee", boot_path],
            input=content.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise PermissionError(f"Cannot write to {boot_path}: {result.stderr.decode(errors='ignore')}")


def remove_i2s_overlays(lines):
    """Remove all I2S-related dtoverlay entries from config lines."""
    new_lines = []
    for line in lines:
        is_i2s_overlay = any(
            re.match(pattern, line.strip(), re.IGNORECASE)
            for pattern in I2S_OVERLAY_PATTERNS
        )
        if not is_i2s_overlay:
            new_lines.append(line)
    return new_lines


def configure_audio_output(audio_option):
    """
    Configure Raspberry Pi audio output by modifying the boot config
    file (real /boot/firmware/config.txt on the Pi, a local mock file
    in dev mode).

    Hardware interface flags (i2c_arm, i2s, spi) now come from the
    consolidated config store instead of .env - see
    spotify_client/config_store.py.

    Args:
        audio_option: Key from AUDIO_OPTIONS, or any custom dtoverlay
                      string if it isn't one of the known keys (kept
                      for boards not in the preset list).

    Returns:
        tuple: (success: bool, message: str)
    """
    if audio_option in AUDIO_OPTIONS:
        audio_config = AUDIO_OPTIONS[audio_option]
    else:
        audio_config = {
            "name": f"Custom DAC ({audio_option})",
            "dtoverlay": audio_option,
            "description": f"Custom I2S DAC: {audio_option}",
        }

    try:
        backup_config()

        config_content = read_config()
        lines = config_content.split("\n")

        lines = remove_i2s_overlays(lines)

        dtoverlay = audio_config.get("dtoverlay")

        hardware = config_store.load_store().get("hardware", {})
        i2c_enabled = bool(hardware.get("i2c_arm_enabled", True))
        i2s_enabled = bool(hardware.get("i2s_enabled", True))
        spi_enabled = bool(hardware.get("spi_enabled", True))

        # Onboard audio: off when an I2S DAC is selected, on for analog,
        # off for HDMI/anything else - same defaulting as before, just
        # no env var escape hatch (not needed now the store holds it).
        if dtoverlay:
            audio_enabled = False
        elif audio_option == "analog":
            audio_enabled = True
        else:
            audio_enabled = False

        new_lines = []
        has_i2c = False
        has_i2s = False
        has_spi = False

        for line in lines:
            stripped = line.strip()
            if re.match(r"#?\s*dtparam\s*=\s*i2c_arm\s*=", stripped, re.IGNORECASE):
                has_i2c = True
                new_lines.append("dtparam=i2c_arm=on" if i2c_enabled else _commented(line))
            elif re.match(r"#?\s*dtparam\s*=\s*i2s\s*=", stripped, re.IGNORECASE):
                has_i2s = True
                new_lines.append("dtparam=i2s=on" if i2s_enabled else _commented(line))
            elif re.match(r"#?\s*dtparam\s*=\s*spi\s*=", stripped, re.IGNORECASE):
                has_spi = True
                new_lines.append("dtparam=spi=on" if spi_enabled else _commented(line))
            elif re.match(r"#?\s*dtparam\s*=\s*audio\s*=", stripped, re.IGNORECASE):
                new_lines.append("dtparam=audio=on" if audio_enabled else _commented(line))
            else:
                new_lines.append(line)

        insert_idx = len(new_lines)
        for i, line in enumerate(new_lines):
            if re.match(r"dtparam\s*=", line.strip(), re.IGNORECASE) and not line.strip().startswith("#"):
                insert_idx = i
                break

        if not has_i2c and i2c_enabled:
            new_lines.insert(insert_idx, "dtparam=i2c_arm=on")
            insert_idx += 1
        if not has_i2s and i2s_enabled:
            new_lines.insert(insert_idx, "dtparam=i2s=on")
            insert_idx += 1
        if not has_spi and spi_enabled:
            new_lines.insert(insert_idx, "dtparam=spi=on")
            insert_idx += 1

        audio_param_exists = any(
            re.match(r"#?\s*dtparam\s*=\s*audio\s*=", line.strip(), re.IGNORECASE)
            for line in new_lines
        )
        if not audio_param_exists and audio_enabled:
            insert_idx = len(new_lines)
            for i, line in enumerate(new_lines):
                if re.match(r"dtparam\s*=\s*spi\s*=\s*on", line.strip(), re.IGNORECASE):
                    insert_idx = i + 1
                    break
            new_lines.insert(insert_idx, "dtparam=audio=on")

        lines = new_lines

        lines = [line for line in lines if not re.match(r"dtoverlay\s*=", line.strip(), re.IGNORECASE)]
        if dtoverlay:
            while lines and lines[-1].strip() == "":
                lines.pop()
            lines.append(f"dtoverlay={dtoverlay}")

        write_config("\n".join(lines))

        suffix = "" if config_store.get_env_mode() == "pi" else " (dev mode: written to mock config file)"
        return True, f"Audio output configured: {audio_config['name']}. Reboot required for changes to take effect.{suffix}"

    except PermissionError as e:
        return False, f"Permission denied: {e}. Ensure the SpotiPi service has root/sudo permissions."
    except Exception as e:
        return False, f"Error configuring audio: {str(e)}"


def _commented(line):
    """Comment out a config line if it isn't already commented."""
    if line.strip().startswith("#"):
        return line
    return "#" + line.lstrip()


def get_audio_options():
    """Get list of available audio options for display."""
    return [
        {
            "value": key,
            "name": value["name"],
            "description": value["description"],
        }
        for key, value in AUDIO_OPTIONS.items()
    ]