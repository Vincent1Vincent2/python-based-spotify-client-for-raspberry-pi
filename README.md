# Spotify Client - Django Web App

A lightweight Django-based Spotify client designed to run on a Raspberry Pi. Control your Spotify playback through a simple web interface.

## Features

- 🎵 Play/Pause controls
- ⏮️⏭️ Skip tracks (previous/next)
- 🔍 Search and queue songs
- 📊 Real-time playback status
- 🎨 Clean, modern web interface
- 🍓 Lightweight for Raspberry Pi

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Spotify API Setup

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Note your Client ID and Client Secret
4. Add `http://127.0.0.1:8000/callback` (or your Raspberry Pi IP) to Redirect URIs

   **Important**: Spotify requires using explicit IP addresses (127.0.0.1) instead of localhost. For production on Raspberry Pi, use your Pi's IP address or HTTPS.

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Generate a Django secret key (or use the script):

```bash
python generate_secret_key.py
```

Or use Python directly:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Edit `.env` with your credentials (paste the generated secret key):

```
SECRET_KEY=your-generated-secret-key-here
DEBUG=True
SPOTIFY_CLIENT_ID=your-client-id-here
SPOTIFY_CLIENT_SECRET=your-client-secret-here
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/callback
```

For Raspberry Pi, update the redirect URI to your Pi's IP address:

```
SPOTIFY_REDIRECT_URI=http://YOUR_PI_IP:8000/callback
```

### 4. Run Migrations

```bash
python manage.py migrate
```

### 5. Start the Server

```bash
python manage.py runserver 0.0.0.0:8000
```

For Raspberry Pi, you might want to run it on all interfaces so you can access it from other devices:

```bash
python manage.py runserver 0.0.0.0:8000
```

### 6. Access the Client

Open your browser and go to:
- Local: `http://127.0.0.1:8000`
- From another device: `http://YOUR_PI_IP:8000`

Click "Login" to authenticate with Spotify.

## Usage

1. **Login**: Click the login button to authenticate with Spotify
2. **Control Playback**: Use Play/Pause, Previous, and Next buttons
3. **Search**: Type a song name in the search box and click Search
4. **Queue Songs**: Click on any search result to add it to your queue

## Running on Raspberry Pi

This client is designed to be lightweight and suitable for Raspberry Pi. For production use on a Pi, consider:

1. Using a production WSGI server like Gunicorn:
   ```bash
   pip install gunicorn
   gunicorn spotify_client.wsgi:application --bind 0.0.0.0:8000
   ```

2. Setting up as a systemd service for auto-start on boot

3. Using Nginx as a reverse proxy for better performance

## Requirements

- Python 3.8+
- Django 5.0+
- Spotify Premium account (required for playback control)

