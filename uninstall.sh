#!/bin/bash
#
# RTSP Audio Streamer Uninstall Script
# Reverses everything install.sh sets up: stops/disables/removes the
# mediamtx and audio-rtsp systemd services, removes the MediaMTX binary,
# and removes the hardware watchdog override.
#
# Usage:
#   chmod +x uninstall.sh
#   ./uninstall.sh
#
# Run as your normal user (NOT root) - it will use sudo where needed.

set -e

HOME_DIR="$HOME"

echo "=== RTSP Audio Streamer Uninstall ==="
echo ""

# 1. Stop and disable services
echo ">>> Stopping and disabling services..."
sudo systemctl disable --now audio-rtsp 2>/dev/null || true
sudo systemctl disable --now mediamtx 2>/dev/null || true

# 2. Remove systemd unit files
echo ">>> Removing systemd unit files..."
sudo rm -f /etc/systemd/system/audio-rtsp.service
sudo rm -f /etc/systemd/system/mediamtx.service
sudo systemctl daemon-reload
sudo systemctl reset-failed audio-rtsp mediamtx 2>/dev/null || true

# 3. Remove MediaMTX binary and config
echo ">>> Removing MediaMTX binary and config..."
rm -f "$HOME_DIR/mediamtx" "$HOME_DIR/mediamtx.yml"

# 4. Remove hardware watchdog override
echo ""
echo ">>> Removing hardware watchdog override..."
sudo rm -f /etc/systemd/system.conf.d/50-watchdog-override.conf
sudo rmdir --ignore-fail-on-non-empty /etc/systemd/system.conf.d 2>/dev/null || true

echo ""
echo "=== Uninstall complete ==="
echo "Note: the RuntimeWatchdogSec change needs 'sudo systemctl daemon-reexec' or a reboot to fully revert in the running system."
echo "Note: ffmpeg, alsa-utils, and wget were left installed (shared system packages)."
echo "      Remove manually if desired: sudo apt remove ffmpeg alsa-utils wget"
