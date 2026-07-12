#!/bin/bash
#
# RTSP Audio Streamer Setup Script
# Turns a Raspberry Pi (Zero W, Zero 2W, 4, etc.) into a headless USB mic -> RTSP streamer.
# Tested on Debian/Raspberry Pi OS (armv6, arm64).
#
# Usage:
#   chmod +x install_rtsp_streamer.sh
#   ./install_rtsp_streamer.sh
#
# Run as your normal user (NOT root) - it will use sudo where needed.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MEDIAMTX_VERSION="v1.19.2"
USER_NAME="$(whoami)"
HOME_DIR="$HOME"
RTSP_PORT=8554
STREAM_PATH="mic"

case "$(uname -m)" in
    aarch64) MEDIAMTX_ARCH="arm64" ;;
    armv6l)  MEDIAMTX_ARCH="armv6" ;;
    armv7l)  MEDIAMTX_ARCH="armv7" ;;
    x86_64)  MEDIAMTX_ARCH="amd64" ;;
    *)
        echo "!!! Unsupported architecture: $(uname -m)"
        exit 1
        ;;
esac
MEDIAMTX_URL="https://raw.githubusercontent.com/chrismyers2000/BirdStreamer/main/vendor/mediamtx/mediamtx_${MEDIAMTX_VERSION}_linux_${MEDIAMTX_ARCH}.tar.gz"
MEDIAMTX_VENDORED="${SCRIPT_DIR}/vendor/mediamtx/mediamtx_${MEDIAMTX_VERSION}_linux_${MEDIAMTX_ARCH}.tar.gz"

echo "=== RTSP Audio Streamer Setup ==="
echo "User: $USER_NAME"
echo "Home: $HOME_DIR"
echo ""

# 1. Update system + install dependencies
echo ">>> Installing ffmpeg and ALSA tools..."
sudo apt update
sudo apt install -y ffmpeg alsa-utils wget

# 2. Detect USB microphone
echo ""
echo ">>> Detecting audio capture devices..."
arecord -l || true
echo ""

CARD_NAME=$(arecord -l | grep -oP '^card \d+: \K\S+' | head -n1)

if [ -z "$CARD_NAME" ]; then
    echo "!!! No capture device detected. Plug in your USB mic and re-run this script."
    exit 1
fi

echo "Detected card name: $CARD_NAME"
echo "This will be used as: plughw:CARD=${CARD_NAME},DEV=0"
echo ""
read -p "Press Enter to continue, or Ctrl+C to abort..."

ALSA_DEVICE="plughw:CARD=${CARD_NAME},DEV=0"

# 3. Download and set up MediaMTX
echo ""
echo ">>> Installing MediaMTX ${MEDIAMTX_VERSION}..."
cd "$HOME_DIR"
if [ ! -f "$HOME_DIR/mediamtx" ]; then
    if [ -f "$MEDIAMTX_VENDORED" ]; then
        echo "Using vendored copy: $MEDIAMTX_VENDORED"
        cp "$MEDIAMTX_VENDORED" mediamtx.tar.gz
    else
        wget -q "$MEDIAMTX_URL" -O mediamtx.tar.gz
    fi
    tar -xzf mediamtx.tar.gz
    rm mediamtx.tar.gz
else
    echo "mediamtx binary already present, skipping download."
fi

# 4. Create systemd service for MediaMTX
echo ""
echo ">>> Creating mediamtx.service..."
sudo tee /etc/systemd/system/mediamtx.service > /dev/null <<EOF
[Unit]
Description=MediaMTX RTSP Server
After=network.target

[Service]
ExecStart=${HOME_DIR}/mediamtx ${HOME_DIR}/mediamtx.yml
Restart=always
User=${USER_NAME}

[Install]
WantedBy=multi-user.target
EOF

# 5. Create systemd service for the audio publisher
echo ">>> Creating audio-rtsp.service..."
sudo tee /etc/systemd/system/audio-rtsp.service > /dev/null <<EOF
[Unit]
Description=Audio RTSP Publisher
After=mediamtx.service sound.target
Requires=mediamtx.service
StartLimitIntervalSec=120
StartLimitBurst=10

[Service]
ExecStartPre=/bin/sleep 10
ExecStart=/usr/bin/ffmpeg -f alsa -ar 48000 -ac 1 -use_wallclock_as_timestamps 1 -i ${ALSA_DEVICE} -acodec pcm_s16be -f rtsp rtsp://localhost:${RTSP_PORT}/${STREAM_PATH}
Restart=always
RestartSec=5
User=${USER_NAME}

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable and start both services
echo ""
echo ">>> Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable --now mediamtx
sudo systemctl enable --now audio-rtsp

# 7. Hardware watchdog (systemd-managed, 15s timeout)
echo ""
echo ">>> Configuring hardware watchdog (15s timeout via systemd)..."
sudo mkdir -p /etc/systemd/system.conf.d
sudo tee /etc/systemd/system.conf.d/50-watchdog-override.conf > /dev/null <<EOF
[Manager]
RuntimeWatchdogSec=15
EOF

# Remove the standalone watchdog package if present - systemd handles it natively
if dpkg -l | grep -q '^ii.*\bwatchdog\b'; then
    echo ">>> Removing redundant standalone watchdog package..."
    sudo systemctl disable --now watchdog 2>/dev/null || true
    sudo apt remove -y watchdog
fi
sudo rm -f /etc/init.d/watchdog

# 8. Summary
echo ""
echo "=== Setup complete ==="
echo "Stream URL:  rtsp://$(hostname -I | awk '{print $1}'):${RTSP_PORT}/${STREAM_PATH}"
echo ""
echo "Reboot now to apply the watchdog timeout and verify everything auto-starts:"
echo "  sudo reboot"
echo ""
echo "After reboot, check status with:"
echo "  sudo systemctl status mediamtx audio-rtsp"
echo "  dmesg | grep -i watchdog"
