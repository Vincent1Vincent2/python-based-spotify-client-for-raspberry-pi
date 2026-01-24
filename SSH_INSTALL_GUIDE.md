# SSH Installation Guide - Where to Put Files

## Quick Answer

**Transfer the entire `spotipy` folder to the Pi, then run the install script from there.**

## Step-by-Step Instructions (Recommended: Zip Method)

### On Your Windows Computer:

1. **Open PowerShell** in the folder containing your SpotiPi code:
   ```powershell
   cd C:\Users\vince\Desktop\spotipy
   ```

2. **Create a zip archive:**
   ```powershell
   Compress-Archive -Path * -DestinationPath spotipy.zip
   ```

3. **Transfer the zip file to the Pi:**
   ```powershell
   # Replace with your actual username and IP
   scp spotipy.zip username@192.168.X.XX:/tmp/
   ```
   
   **Note:** Replace `username` and `192.168.X.XX` with your Pi's actual username and IP address.

### On the Raspberry Pi (via SSH):

1. **SSH into the Pi:**
   ```bash
   # Replace with your actual username and IP
   ssh username@192.168.X.XX
   ```

2. **Extract the zip file:**
   ```bash
   cd /tmp
   sudo unzip spotipy.zip -d spotipi
   cd spotipi
   ```

3. **Verify the files are there:**
   ```bash
   ls -la
   ```
   
   You should see files like:
   - `install.sh`
   - `prepare_image.sh`
   - `manage.py`
   - `requirements.txt`
   - `player/` directory
   - `wizard/` directory
   - etc.

4. **Make the install script executable:**
   ```bash
   sudo chmod +x install.sh
   ```

5. **Run the installation:**
   ```bash
   sudo ./install.sh
   ```

6. **After installation completes, clean up temporary files:**
   ```bash
   cd ~
  sudo rm -rf /tmp/spotipi /tmp/spotipy.zip
   ```

## Alternative Methods

### Direct Transfer (without zip)

If you prefer to transfer files directly:

**On Windows:**
```powershell
cd C:\Users\vince\Desktop\spotipy
scp -r . pi@raspberrypi.local:/tmp/spotipi
```

**On Pi:**
```bash
cd /tmp/spotipi
```

### Using Git (if your code is in a repository)

If your SpotiPi code is in a Git repository:

```bash
# On the Pi via SSH:
cd /tmp
git clone <your-repo-url> spotipi
cd spotipi
chmod +x install.sh
sudo ./install.sh
```

## Alternative: Using USB Drive

1. Copy the `spotipy` folder to a USB drive on your Windows computer
2. Plug USB drive into the Pi
3. On the Pi:
   ```bash
   # Find the USB drive (usually /media/pi/...)
   ls /media/pi/
   
   # Copy files
   cp -r /media/pi/USBNAME/spotipy /tmp/spotipi
   cd /tmp/spotipi
   chmod +x install.sh
   sudo ./install.sh
   ```

## What Happens During Installation

The `install.sh` script will:
- Install system dependencies (Python, pip, etc.)
- Copy all files from the current directory to `/opt/spotipi` (the final location)
- Create a Python virtual environment
- Install Python packages
- Set up the systemd service
- Start the SpotiPi service

**The app will be installed to `/opt/spotipi`** - you don't need to manually move files there, the script does it.

## After Installation

- The app runs from: `/opt/spotipi`
- Service name: `spotipi`
- Access at: `http://<pi-ip-address>:8000`

## Troubleshooting

**"Permission denied" when running install.sh:**
- Make sure you used `chmod +x install.sh`
- Make sure you're using `sudo ./install.sh`

**"No such file or directory":**
- Make sure you're in the right directory: `cd /tmp/spotipi`
- Check files are there: `ls -la`

**scp command not found on Windows:**
- Use WinSCP (GUI tool) instead
- Or use Git to clone the repository
- Or use a USB drive

