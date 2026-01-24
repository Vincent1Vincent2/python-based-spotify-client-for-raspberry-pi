#!/bin/bash

# SpotiPi Installation Script
# This script installs SpotiPi on a Raspberry Pi running Raspberry Pi OS
# Run with: sudo ./install.sh

set -e  # Exit on error

echo "=========================================="
echo "SpotiPi Installation Script"
echo "=========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Detect the actual user (who invoked sudo, or first non-root user)
if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
elif [ -n "$USER" ] && [ "$USER" != "root" ]; then
    ACTUAL_USER="$USER"
else
    # Try to find the first non-root user with a home directory
    ACTUAL_USER=$(getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 {print $1; exit}')
    if [ -z "$ACTUAL_USER" ]; then
        ACTUAL_USER="pi"  # Fallback to pi if nothing found
    fi
fi

ACTUAL_USER_HOME=$(eval echo ~$ACTUAL_USER)

echo "Detected user: $ACTUAL_USER"
echo "User home: $ACTUAL_USER_HOME"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INSTALL_DIR="/opt/spotipi"

echo ""
echo "Step 1: Installing system dependencies..."
apt update
apt install -y python3 python3-pip python3-venv git alsa-utils iw wireless-tools

# Check if we're on a desktop or lite version and install X if needed
HAS_DESKTOP=$(dpkg -l 2>/dev/null | grep -q "raspberrypi-ui-mods" && echo "yes" || echo "no")
HAS_X=$(dpkg -l 2>/dev/null | grep -q "xserver-xorg" && echo "yes" || echo "no")
if [ "$HAS_X" = "no" ]; then
    echo ""
    echo "Detected Raspberry Pi OS Lite - Installing X server for local display..."
    apt install -y xserver-xorg xinit x11-xserver-utils unclutter
    # Verify the detected user exists
    if ! id -u "$ACTUAL_USER" &> /dev/null; then
        echo "Warning: User '$ACTUAL_USER' not found. Desktop auto-launch may not work."
    fi
else
    echo ""
    echo "Desktop environment detected - Installing additional X utilities..."
    apt install -y unclutter
fi

# Install browser for kiosk mode
echo ""
echo "Installing browser for kiosk mode..."
if command -v chromium-browser &> /dev/null; then
    echo "Chromium already installed"
elif command -v chromium &> /dev/null; then
    echo "Chromium already installed"
else
    apt install -y chromium-browser || apt install -y chromium
fi

echo ""
echo "Step 2: Creating installation directory..."
mkdir -p "$INSTALL_DIR"

echo ""
echo "Step 3: Copying application files..."
# Copy all files except certain directories
if command -v rsync &> /dev/null; then
    rsync -av --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='db.sqlite3' --exclude='staticfiles' "$SCRIPT_DIR/" "$INSTALL_DIR/"
else
    # Fallback to cp if rsync is not available
    echo "rsync not found, using cp instead..."
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
    # Remove unwanted files/directories
    rm -rf "$INSTALL_DIR/venv" "$INSTALL_DIR/__pycache__" "$INSTALL_DIR/db.sqlite3" "$INSTALL_DIR/staticfiles"
    find "$INSTALL_DIR" -name "*.pyc" -delete
fi

echo ""
echo "Step 4: Creating virtual environment..."
cd "$INSTALL_DIR"
python3 -m venv venv

echo ""
echo "Step 5: Installing Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r requirements.txt

echo ""
echo "Step 6: Creating configuration directory..."
mkdir -p /etc/spotipi
chmod 755 /etc/spotipi

echo ""
echo "Step 7: Setting up database..."
"$INSTALL_DIR/venv/bin/python" manage.py migrate --noinput

echo ""
echo "Step 8: Collecting static files..."
"$INSTALL_DIR/venv/bin/python" manage.py collectstatic --noinput

echo ""
echo "Step 9: Creating systemd service..."
cat > /etc/systemd/system/spotipi.service << EOF
[Unit]
Description=SpotiPi Django Application
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$INSTALL_DIR/venv/bin/python manage.py runserver 0.0.0.0:8000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "Step 10: Enabling and starting service..."
systemctl daemon-reload
systemctl enable spotipi.service
systemctl start spotipi.service

echo ""
echo "Step 11: Setting file permissions..."
chown -R root:root "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

echo ""
echo "Step 12: Setting up browser auto-launch for local display..."
# Create a script to launch the browser in kiosk mode
cat > /usr/local/bin/spotipi-browser.sh << 'BROWSER_EOF'
#!/bin/bash
# Wait for the Django server to be ready
echo "Waiting for SpotiPi service to start..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000 > /dev/null 2>&1; then
        echo "SpotiPi is ready!"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 2
done

# Wait a bit for desktop to be fully loaded
sleep 3

# Set DISPLAY if not set (for desktop environment)
if [ -z "$DISPLAY" ]; then
    # Try to find the display from a logged-in user
    DISPLAY=$(who | awk '{print $2}' | grep -E '^:[0-9]+' | head -1)
    if [ -n "$DISPLAY" ]; then
        export DISPLAY
    else
        # Fallback to :0 (most common)
        export DISPLAY=:0
    fi
fi

# Check if we have a display
if ! xset q &>/dev/null; then
    echo "Error: No X display available. Make sure you're logged in to the desktop."
    exit 1
fi

# Disable screen blanking
xset s off 2>/dev/null || true
xset -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true

# Hide cursor after 3 seconds of inactivity
unclutter -idle 3 -root & 2>/dev/null || true

# Determine which browser to use
if command -v chromium-browser &> /dev/null; then
    BROWSER="chromium-browser"
elif command -v chromium &> /dev/null; then
    BROWSER="chromium"
else
    echo "No suitable browser found!"
    exit 1
fi

# Launch browser in kiosk mode
$BROWSER --noerrdialogs --disable-infobars --kiosk http://127.0.0.1:8000
BROWSER_EOF

chmod +x /usr/local/bin/spotipi-browser.sh

# Create autostart for desktop environment
AUTOSTART_DIR="$ACTUAL_USER_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/spotipi.desktop" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=SpotiPi
Exec=/usr/local/bin/spotipi-browser.sh
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
DESKTOP_EOF

chown -R "$ACTUAL_USER:$ACTUAL_USER" "$ACTUAL_USER_HOME/.config" 2>/dev/null || true

# For Lite version (no desktop), set up X auto-start
if [ "$HAS_DESKTOP" = "no" ]; then
    echo "Setting up X auto-start for Lite version..."
    
    # Create .xinitrc
    if [ ! -f "$ACTUAL_USER_HOME/.xinitrc" ] || ! grep -q "spotipi-browser" "$ACTUAL_USER_HOME/.xinitrc" 2>/dev/null; then
        cat > "$ACTUAL_USER_HOME/.xinitrc" << XINIT_EOF
#!/bin/sh
# Start SpotiPi browser
/usr/local/bin/spotipi-browser.sh
XINIT_EOF
        chmod +x "$ACTUAL_USER_HOME/.xinitrc"
        chown "$ACTUAL_USER:$ACTUAL_USER" "$ACTUAL_USER_HOME/.xinitrc"
    fi

    # Enable autologin for the detected user
    if [ ! -f /etc/systemd/system/getty@tty1.service.d/autologin.conf ]; then
        mkdir -p /etc/systemd/system/getty@tty1.service.d
        cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << AUTOLOGIN_EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $ACTUAL_USER --noclear %I \$TERM
AUTOLOGIN_EOF
        systemctl daemon-reload
    fi

    # Create .bash_profile to auto-start X on login
    if [ ! -f "$ACTUAL_USER_HOME/.bash_profile" ] || ! grep -q "startx" "$ACTUAL_USER_HOME/.bash_profile" 2>/dev/null; then
        cat >> "$ACTUAL_USER_HOME/.bash_profile" << BASHPROFILE_EOF

# Auto-start X on tty1 if not already running
if [ -z "\$DISPLAY" ] && [ "\$(tty)" = "/dev/tty1" ]; then
    startx
fi
BASHPROFILE_EOF
        chown "$ACTUAL_USER:$ACTUAL_USER" "$ACTUAL_USER_HOME/.bash_profile"
    fi
else
    echo "Desktop environment detected - Using autostart for browser launch."
fi

echo ""
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo ""
echo "SpotiPi has been installed to: $INSTALL_DIR"
echo "Service status: $(systemctl is-active spotipi)"
echo ""
echo "The application is accessible at:"
echo "  Local: http://127.0.0.1:8000"
echo "  Network: http://<pi-ip-address>:8000"
echo ""
echo "Browser will auto-launch on boot in kiosk mode for local display."
echo ""
echo "To check the service status:"
echo "  sudo systemctl status spotipi"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u spotipi -f"
echo ""
echo "To manually launch browser:"
echo "  /usr/local/bin/spotipi-browser.sh"
echo ""
echo "The setup wizard will appear on first access."
echo ""

