# SpotiPi - Raspberry Pi Spotify Client

A lightweight Django-based Spotify client designed to run on Raspberry Pi. Control your Spotify playback through a simple web interface with full support for I2S DACs, WiFi configuration, and custom OS image distribution.

## Features

- 🎵 **Full Spotify Control**: Play/Pause, Skip tracks, Queue management
- 🎧 **Audio Output Selection**: Built-in 3.5mm jack, HDMI, or I2S DAC support
  - HiFiBerry DAC+ (basic, Light, Pro)
  - IQaudio DAC+
  - JustBoom DAC
  - Allo Boss/Boss2 DAC
- 📡 **WiFi Configuration**: Integrated WiFi setup wizard with network scanning
- 🔧 **First-Boot Setup Wizard**: Complete configuration in one place
- 🎨 **Modern Minimalist UI**: Clean, simple design
- 🍓 **Lightweight**: Optimized for Raspberry Pi
- 🖥️ **Web Playback SDK**: Play audio directly in browser or control other devices
- 📱 **Multi-Device Support**: Switch between Web Player and other Spotify Connect devices

## Setup

### For End Users (OS Image)

1. **Download the SpotiPi OS Image**
   - Download the latest image from releases
   - Flash to SD card using Raspberry Pi Imager or similar tool

2. **Boot Your Raspberry Pi**
   - Insert SD card and power on
   - The system will automatically start the setup wizard

3. **Complete Setup Wizard**
   - Configure WiFi (optional if using Ethernet)
   - Enter Spotify API credentials (Client ID, Client Secret, Redirect URI)
   - Select audio output device
   - Save configuration

4. **Access the Client**
   - Open browser and navigate to `http://<pi-ip-address>:8000`
   - Login with Spotify
   - Start controlling playback!

### For Developers (Manual Installation)

#### 1. Install Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git alsa-utils
pip install -r requirements.txt
```

#### 2. Spotify API Setup

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Note your Client ID and Client Secret
4. Add redirect URI: `http://<your-pi-ip>:8000/callback`

#### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Generate a Django secret key (optional, can use the script):

```bash
python generate_secret_key.py
```

Edit `.env` with your credentials:

```
SECRET_KEY=your-generated-secret-key-here
DEBUG=True
SPOTIFY_CLIENT_ID=your-client-id-here
SPOTIFY_CLIENT_SECRET=your-client-secret-here
SPOTIFY_REDIRECT_URI=http://<your-pi-ip>:8000/callback
```

For production (Raspberry Pi OS image), configuration is stored in `/etc/spotipi/spotipi.conf` and managed through the setup wizard.

#### 4. Run Migrations

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

#### 5. Start the Server

**Development:**
```bash
python manage.py runserver 0.0.0.0:8000
```

**Production (systemd service):**
Create `/etc/systemd/system/spotipi.service`:

```ini
[Unit]
Description=SpotiPi Django Application
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/spotipi
Environment="PATH=/opt/spotipi/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/spotipi/venv/bin/python manage.py runserver 0.0.0.0:8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable spotipi.service
sudo systemctl start spotipi.service
```

#### 6. Access the Client

Open your browser and go to:
- Local: `http://127.0.0.1:8000`
- From another device: `http://<pi-ip-address>:8000`

Click "Login" to authenticate with Spotify.

## Setup Wizard

The first-boot setup wizard provides a complete configuration experience:

1. **WiFi Configuration** (optional)
   - Auto-scans for available networks
   - Select network from dropdown or enter manually
   - Enter WiFi password
   - Option to skip if using Ethernet

2. **Spotify Configuration**
   - Enter Client ID and Client Secret from Spotify Developer Dashboard
   - Redirect URI (auto-detected or enter manually)
   - Automatically generates Django SECRET_KEY

3. **Audio Output Selection**
   - **3.5mm Analog Jack** (default)
   - **HDMI Audio**
   - **I2S DAC** (with model selection dropdown)
     - HiFiBerry DAC+
     - HiFiBerry DAC+ Light
     - HiFiBerry DAC+ Pro
     - IQaudio DAC+
     - JustBoom DAC
     - Allo Boss DAC
     - Allo Boss2 DAC

The wizard automatically configures:
- `/etc/wpa_supplicant/wpa_supplicant.conf` (WiFi)
- `/boot/config.txt` (Audio output/I2S DACs)
- `/etc/spotipi/spotipi.conf` (App configuration)
- Django SECRET_KEY (auto-generated)

## Usage

1. **Login**: Click the login button to authenticate with Spotify
2. **Control Playback**: Use Play/Pause, Previous, and Next buttons
3. **Browse Content**: 
   - **Playlists**: Browse and play your playlists
   - **Albums**: Browse and play your saved albums
   - **Songs**: Browse and play your saved tracks
   - **Discover**: Explore random recommendations
4. **Device Management**: Switch between Web Player and other Spotify Connect devices
5. **Search**: Search for tracks, albums, artists, or playlists
6. **Queue Management**: Add tracks to your queue

## Audio Output Configuration

The setup wizard automatically configures your Raspberry Pi's audio output by modifying `/boot/config.txt`:

- **3.5mm Analog Jack**: Default output, no changes needed
- **HDMI Audio**: Configures for HDMI output
- **I2S DACs**: Adds appropriate `dtoverlay` entries for your specific DAC model

**Important**: A reboot is required for audio configuration changes to take effect.

## Requirements

- Python 3.8+
- Django 5.0+
- Spotify Premium account (required for playback control)
- Raspberry Pi (3B+, 4, 5, or Zero 2 W recommended)
- Raspberry Pi OS Lite or Desktop (64-bit recommended)

## Project Structure

```
spotipy/
├── player/              # Main Django app
│   ├── static/         # CSS files (variables, base, player, login)
│   ├── templates/      # HTML templates
│   ├── spotify_api.py  # Custom Spotify API client
│   └── views.py        # Main application logic
├── wizard/             # Setup wizard app
│   ├── static/         # Wizard CSS
│   ├── templates/      # Wizard templates
│   ├── audio_config.py # Audio/I2S configuration
│   ├── wifi_config.py  # WiFi configuration
│   └── views.py        # Wizard logic
├── spotify_client/     # Django project settings
│   ├── config.py       # Configuration management
│   └── settings.py     # Django settings
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

## Creating an OS Image

To create a custom Raspberry Pi OS image with SpotiPi pre-installed:

1. **Start with Raspberry Pi OS Lite** (64-bit recommended)
2. **Install dependencies** (see Setup section)
3. **Copy application** to `/opt/spotipi`
4. **Set up systemd service** (see Production section)
5. **Test everything** works correctly
6. **Clean up system** (clear logs, temp files, etc.)
7. **Create disk image** using Raspberry Pi Imager or `dd`
8. **Test the image** on a fresh SD card

See documentation for detailed image creation process.

## Development

### Running Locally (Development)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Run development server
python manage.py runserver 0.0.0.0:8000
```

### Configuration Files

- **Development**: `.env` file (not tracked in git)
- **Production**: `/etc/spotipi/spotipi.conf` (managed by setup wizard)

### Environment Variables

- `SECRET_KEY`: Django secret key (auto-generated in wizard)
- `DEBUG`: Enable debug mode (True/False)
- `SPOTIFY_CLIENT_ID`: Spotify API Client ID
- `SPOTIFY_CLIENT_SECRET`: Spotify API Client Secret
- `SPOTIFY_REDIRECT_URI`: OAuth redirect URI

## License

[Your License Here]

## Contributing

[Contributing Guidelines Here]

## Support

[Support Information Here]
