#!/usr/bin/env python3
#
# RTSP Audio Streamer Setup Script (Python port of install.sh)
# Turns a Raspberry Pi (Zero 2 W, 4, etc.) into a headless USB mic -> RTSP streamer.
# Tested on Debian/Raspberry Pi OS (armv6, arm64).
#
# NOT SUPPORTED: the original Raspberry Pi Zero W. Its single-core CPU can't
# reliably run ffmpeg + MediaMTX at once - confirmed via testing: CPU pegged
# at 100%, stream intermittent. Use a Zero 2 W or newer instead.
#
# Usage:
#   chmod +x install.py
#   ./install.py
#
# Or as a single command:
#   curl -fsSL https://raw.githubusercontent.com/chrismyers2000/BirdStreamer/main/install.py | python3
#
# Run as your normal user (NOT root) - it will use sudo where needed.

import importlib.util
import os
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

# Without this, a stalled connection (not an error, just no data ever
# arriving - seen in practice on a flaky Wi-Fi link) leaves urlretrieve
# hanging forever with no feedback. 30s is generous for a single HTTP
# request/small-file fetch; MediaMTX's ~28MB tarball still finishes in a
# few seconds on a normal connection.
socket.setdefaulttimeout(30)
from pathlib import Path

MEDIAMTX_VERSION = "v1.19.2"
RTSP_PORT = 8554
STREAM_PATH = "mic"


def run(cmd, **kwargs):
    kwargs.setdefault("check", True)
    return subprocess.run(cmd, **kwargs)


def sudo_write(path, content):
    subprocess.run(["sudo", "tee", path], input=content, text=True,
                    stdout=subprocess.DEVNULL, check=True)


def fetch_repo_file(dest, filename, script_dir):
    """Copy filename from a local checkout (script_dir) if present, else
    download it from this repo's own GitHub mirror - same vendored-or-mirror
    pattern used for the MediaMTX binaries. Uses the GitHub Contents API
    rather than raw.githubusercontent.com: confirmed in practice that the
    raw CDN caches for up to 5 minutes and ignores both cache-busting query
    params and no-cache headers, silently serving stale code right after a
    push with no error. The Contents API caches for only ~60s."""
    if script_dir and (script_dir / filename).is_file():
        dest.write_bytes((script_dir / filename).read_bytes())
    else:
        req = urllib.request.Request(
            f"https://api.github.com/repos/chrismyers2000/BirdStreamer/contents/{filename}",
            headers={"Accept": "application/vnd.github.raw"},
        )
        with urllib.request.urlopen(req) as resp:
            dest.write_bytes(resp.read())


def install_sudoers_rule(user_name, audio_service_path):
    """Grant just enough passwordless sudo for the web UI to restart the
    audio service and rewrite its unit file - not blanket sudo access.
    User confirmed this approach explicitly (2026-07-12) over running the
    whole web service as root. Validated with `visudo -c` before ever being
    placed as a live file, since a malformed /etc/sudoers.d file can break
    sudo system-wide."""
    content = (
        f"{user_name} ALL=(ALL) NOPASSWD: "
        f"/usr/bin/tee {audio_service_path}, "
        "/usr/bin/systemctl daemon-reload, "
        "/usr/bin/systemctl start audio-rtsp, "
        "/usr/bin/systemctl stop audio-rtsp, "
        "/usr/bin/systemctl restart audio-rtsp\n"
    )
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sudoers") as f:
        f.write(content)
        tmp_path = f.name
    try:
        run(["sudo", "visudo", "-c", "-f", tmp_path])
        run(["sudo", "install", "-m", "0440", tmp_path, "/etc/sudoers.d/birdstreamer-webui"])
    finally:
        os.unlink(tmp_path)


def print_banner():
    text = "BIRD STREAMER"
    width = 44
    print("=" * width)
    print("||" + text.center(width - 4) + "||")
    print("=" * width)
    print()


def main():
    # Force line buffering even when stdout is piped (e.g. through `tee`),
    # so our prints interleave correctly with subprocess output instead of
    # appearing to run out of order.
    sys.stdout.reconfigure(line_buffering=True)

    print_banner()

    # When piped (e.g. curl ... | python3), stdin is the script itself, not
    # the terminal - reattach stdin to the real tty so input() below still
    # works. Safe in Python (unlike bash): the interpreter has already fully
    # read/compiled the script from stdin before this code runs.
    if not sys.stdin.isatty():
        sys.stdin = open("/dev/tty")

    try:
        script_dir = Path(__file__).resolve().parent
    except NameError:
        script_dir = None  # running via a pipe with no real file on disk

    pi_model = ""
    try:
        pi_model = Path("/proc/device-tree/model").read_bytes().decode(errors="ignore").strip("\x00").strip()
    except FileNotFoundError:
        pass

    if "Zero W" in pi_model and "Zero 2 W" not in pi_model:
        print(f"!!! Unsupported hardware: {pi_model}")
        print("!!! The original Pi Zero W's single-core CPU can't reliably run ffmpeg + MediaMTX")
        print("!!! at the same time - confirmed via testing: CPU pegged at 100%, stream intermittent.")
        print("!!! Use a Raspberry Pi Zero 2 W or newer.")
        sys.exit(1)

    user_name = run(["whoami"], capture_output=True, text=True).stdout.strip()
    home_dir = Path.home()

    machine = os.uname().machine
    arch_map = {
        "aarch64": "arm64",
        "armv6l": "armv6",
        "armv7l": "armv7",
        "x86_64": "amd64",
    }
    mediamtx_arch = arch_map.get(machine)
    if mediamtx_arch is None:
        print(f"!!! Unsupported architecture: {machine}")
        sys.exit(1)

    mediamtx_tarball = f"mediamtx_{MEDIAMTX_VERSION}_linux_{mediamtx_arch}.tar.gz"
    mediamtx_url = f"https://raw.githubusercontent.com/chrismyers2000/BirdStreamer/main/vendor/mediamtx/{mediamtx_tarball}"
    mediamtx_vendored = (script_dir / "vendor" / "mediamtx" / mediamtx_tarball) if script_dir else None

    print("=== RTSP Audio Streamer Setup ===")
    print(f"User: {user_name}")
    print(f"Home: {home_dir}")
    print()

    # 1. Update system + install dependencies
    print(">>> Installing ffmpeg and ALSA tools...")
    run(["sudo", "apt", "update"])
    run(["sudo", "apt", "install", "-y", "ffmpeg", "alsa-utils", "wget", "python3-flask"])

    # 2. Detect USB microphone
    print()
    print(">>> Detecting audio capture devices...")
    arecord_output = run(["arecord", "-l"], capture_output=True, text=True, check=False).stdout
    print(arecord_output)

    seen = set()
    card_lines = []
    for line in arecord_output.splitlines():
        m = re.match(r"^card \d+: \S+ \[[^\]]+\]", line)
        if m and m.group(0) not in seen:
            seen.add(m.group(0))
            card_lines.append(m.group(0))

    if not card_lines:
        print("!!! No capture device detected. Plug in your USB mic and re-run this script.")
        sys.exit(1)
    elif len(card_lines) == 1:
        card_name = re.match(r"^card \d+: (\S+)", card_lines[0]).group(1)
    else:
        print("Multiple capture devices detected:")
        for i, line in enumerate(card_lines):
            print(f"  {i + 1}) {line}")
        print()
        while True:
            selection = input(f"Select the sound card to use [1-{len(card_lines)}]: ")
            if selection.isdigit() and 1 <= int(selection) <= len(card_lines):
                break
            print("Invalid selection, try again.")
        card_name = re.match(r"^card \d+: (\S+)", card_lines[int(selection) - 1]).group(1)

    print(f"Detected card name: {card_name}")
    print(f"This will be used as: plughw:CARD={card_name},DEV=0")
    print()
    input("Press Enter to continue, or Ctrl+C to abort...")

    # 3. Download and set up MediaMTX
    print()
    print(f">>> Installing MediaMTX {MEDIAMTX_VERSION}...")
    os.chdir(home_dir)
    mediamtx_bin = home_dir / "mediamtx"
    tarball_path = home_dir / "mediamtx.tar.gz"
    if not mediamtx_bin.exists():
        if mediamtx_vendored and mediamtx_vendored.is_file():
            print(f"Using vendored copy: {mediamtx_vendored}")
            tarball_path.write_bytes(mediamtx_vendored.read_bytes())
        else:
            urllib.request.urlretrieve(mediamtx_url, tarball_path)
        with tarfile.open(tarball_path, "r:gz") as tar:
            tar.extractall(home_dir, filter="data")
        tarball_path.unlink()
    else:
        print("mediamtx binary already present, skipping download.")

    # Enable MediaMTX's local API (disabled by default) - it's unauthenticated
    # only from 127.0.0.1, so the web control panel can query viewer count /
    # live stream stats without exposing anything externally.
    mediamtx_yml = home_dir / "mediamtx.yml"
    if mediamtx_yml.is_file():
        yml_content = mediamtx_yml.read_text()
        mediamtx_yml.write_text(yml_content.replace("api: false", "api: yes", 1))

    # 4. Create systemd service for MediaMTX
    print()
    print(">>> Creating mediamtx.service...")
    sudo_write("/etc/systemd/system/mediamtx.service", f"""[Unit]
Description=MediaMTX RTSP Server
After=network.target

[Service]
ExecStart={home_dir}/mediamtx {home_dir}/mediamtx.yml
Restart=always
User={user_name}

[Install]
WantedBy=multi-user.target
""")

    # 5. Set up the web control panel (birdstreamer_common.py + webui.py),
    # and use the shared module to build audio-rtsp.service so both the
    # installer and the web UI build it from the exact same config/logic.
    print()
    print(">>> Setting up web control panel...")
    app_dir = home_dir / ".birdstreamer"
    app_dir.mkdir(parents=True, exist_ok=True)
    fetch_repo_file(app_dir / "birdstreamer_common.py", "birdstreamer_common.py", script_dir)
    fetch_repo_file(app_dir / "webui.py", "webui.py", script_dir)

    spec = importlib.util.spec_from_file_location("birdstreamer_common", app_dir / "birdstreamer_common.py")
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)

    config = common.load_config()
    config["card_name"] = card_name
    common.save_config(config)

    print(">>> Creating audio-rtsp.service...")
    common.write_audio_service(config)

    print(">>> Creating birdstreamer-webui.service...")
    sudo_write("/etc/systemd/system/birdstreamer-webui.service", f"""[Unit]
Description=BirdStreamer Web Control Panel
After=network.target

[Service]
ExecStart=/usr/bin/python3 {app_dir}/webui.py
Restart=always
User={user_name}

[Install]
WantedBy=multi-user.target
""")

    print(">>> Configuring sudo permissions for the web control panel...")
    install_sudoers_rule(user_name, common.AUDIO_SERVICE_PATH)

    # 6. Enable and start all services
    print()
    print(">>> Enabling and starting services...")
    run(["sudo", "systemctl", "daemon-reload"])
    run(["sudo", "systemctl", "enable", "--now", "mediamtx"])
    run(["sudo", "systemctl", "enable", "--now", "audio-rtsp"])
    run(["sudo", "systemctl", "enable", "--now", "birdstreamer-webui"])

    # 7. Hardware watchdog (systemd-managed, 15s timeout)
    print()
    print(">>> Configuring hardware watchdog (15s timeout via systemd)...")
    run(["sudo", "mkdir", "-p", "/etc/systemd/system.conf.d"])
    sudo_write("/etc/systemd/system.conf.d/50-watchdog-override.conf", "[Manager]\nRuntimeWatchdogSec=15\n")

    # Remove the standalone watchdog package if present - systemd handles it natively
    dpkg_list = run(["dpkg", "-l"], capture_output=True, text=True, check=False).stdout
    if re.search(r"^ii.*\bwatchdog\b", dpkg_list, re.MULTILINE):
        print(">>> Removing redundant standalone watchdog package...")
        run(["sudo", "systemctl", "disable", "--now", "watchdog"], check=False)
        run(["sudo", "apt", "remove", "-y", "watchdog"])
    run(["sudo", "rm", "-f", "/etc/init.d/watchdog"])

    # 8. Summary
    ip = run(["hostname", "-I"], capture_output=True, text=True).stdout.split()[0]
    print()
    print("=== Setup complete ===")
    print(f"Stream URL:       rtsp://{ip}:{RTSP_PORT}/{STREAM_PATH}")
    print(f"Control panel:    http://{ip}:8080")
    print()
    print("Reboot now to apply the watchdog timeout and verify everything auto-starts:")
    print("  sudo reboot")
    print()
    print("After reboot, check status with:")
    print("  sudo systemctl status mediamtx audio-rtsp birdstreamer-webui")
    print("  dmesg | grep -i watchdog")


if __name__ == "__main__":
    main()
