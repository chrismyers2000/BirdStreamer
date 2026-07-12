#!/usr/bin/env python3
#
# RTSP Audio Streamer Uninstall Script (Python port of uninstall.sh)
# Reverses everything install.py sets up: stops/disables/removes the
# mediamtx and audio-rtsp systemd services, removes the MediaMTX binary,
# and removes the hardware watchdog override.
#
# Usage:
#   chmod +x uninstall.py
#   ./uninstall.py
#
# Or as a single command:
#   curl -fsSL https://raw.githubusercontent.com/chrismyers2000/BirdStreamer/main/uninstall.py | python3
#
# Run as your normal user (NOT root) - it will use sudo where needed.

import subprocess
from pathlib import Path


def run(cmd, **kwargs):
    kwargs.setdefault("check", False)
    return subprocess.run(cmd, **kwargs)


def main():
    home_dir = Path.home()

    print("=== RTSP Audio Streamer Uninstall ===")
    print()

    # 1. Stop and disable services
    print(">>> Stopping and disabling services...")
    run(["sudo", "systemctl", "disable", "--now", "audio-rtsp"], stderr=subprocess.DEVNULL)
    run(["sudo", "systemctl", "disable", "--now", "mediamtx"], stderr=subprocess.DEVNULL)

    # 2. Remove systemd unit files
    print(">>> Removing systemd unit files...")
    run(["sudo", "rm", "-f", "/etc/systemd/system/audio-rtsp.service"])
    run(["sudo", "rm", "-f", "/etc/systemd/system/mediamtx.service"])
    run(["sudo", "systemctl", "daemon-reload"])
    run(["sudo", "systemctl", "reset-failed", "audio-rtsp", "mediamtx"], stderr=subprocess.DEVNULL)

    # 3. Remove MediaMTX binary and config
    print(">>> Removing MediaMTX binary and config...")
    (home_dir / "mediamtx").unlink(missing_ok=True)
    (home_dir / "mediamtx.yml").unlink(missing_ok=True)

    # 4. Remove hardware watchdog override
    print()
    print(">>> Removing hardware watchdog override...")
    run(["sudo", "rm", "-f", "/etc/systemd/system.conf.d/50-watchdog-override.conf"])
    run(["sudo", "rmdir", "--ignore-fail-on-non-empty", "/etc/systemd/system.conf.d"], stderr=subprocess.DEVNULL)

    print()
    print("=== Uninstall complete ===")
    print("Note: the RuntimeWatchdogSec change needs 'sudo systemctl daemon-reexec' or a reboot to fully revert in the running system.")
    print("Note: ffmpeg, alsa-utils, and wget were left installed (shared system packages).")
    print("      Remove manually if desired: sudo apt remove ffmpeg alsa-utils wget")


if __name__ == "__main__":
    main()
