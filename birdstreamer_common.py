#!/usr/bin/env python3
# Shared logic used by both install.py (initial setup) and webui.py (the
# live control panel) so there is exactly one place that builds the
# audio-rtsp.service unit file / ffmpeg command line from the current config.
#
# This module is plain Python with no third-party dependencies (no Flask),
# so install.py can import it safely even outside a virtualenv.

import getpass
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

# Without this, fetch_repo_file()'s download can hang forever on a stalled
# connection (seen in practice on a flaky Wi-Fi link), freezing webui.py's
# self-update request indefinitely. get_mediamtx_status() already sets its
# own shorter per-call timeout, which takes precedence over this default.
socket.setdefaulttimeout(30)

APP_DIR = Path.home() / ".birdstreamer"
CONFIG_PATH = APP_DIR / "config.json"
AUDIO_SERVICE_PATH = "/etc/systemd/system/audio-rtsp.service"
RTSP_PORT = 8554
STREAM_PATH = "mic"
SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000]
GAIN_MIN, GAIN_MAX = 0.5, 4.0
HIGHPASS_FREQ_MIN, HIGHPASS_FREQ_MAX = 20, 1000
DEVICE_NAME_MAX_LEN = 60

# -rtbufsize caps how much audio ffmpeg's ALSA input can queue up before it
# starts dropping samples if something downstream momentarily can't keep up
# (a slow SD card write, a CPU spike, etc). It is not a fixed end-to-end
# delay knob - in normal steady-state operation, audio flows straight
# through and this buffer sits mostly empty. "low" trades away some
# dropout-resistance for a smaller worst-case backlog; "high_stability"
# does the opposite. "balanced" leaves ffmpeg's own default (~3MB) alone.
LATENCY_MODES = {
    "low": 65536,
    "balanced": None,
    "high_stability": 8388608,
}

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/chrismyers2000/BirdStreamer/main"
GITHUB_API_CONTENTS_BASE = "https://api.github.com/repos/chrismyers2000/BirdStreamer/contents"
MEDIAMTX_API_BASE = "http://127.0.0.1:9997"

DEFAULT_CONFIG = {
    "device_name": "BirdStreamer",
    "card_name": None,
    "sample_rate": 48000,
    "gain": 1.0,
    "highpass_enabled": False,
    "highpass_freq": 100,
    "latency_mode": "balanced",
}


def load_config():
    if CONFIG_PATH.exists():
        config = dict(DEFAULT_CONFIG)
        config.update(json.loads(CONFIG_PATH.read_text()))
        return config
    return dict(DEFAULT_CONFIG)


def save_config(config):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def detect_cards():
    """Return a list of {"id": ..., "label": ...} for each detected capture card."""
    output = subprocess.run(["arecord", "-l"], capture_output=True, text=True, check=False).stdout
    seen = set()
    cards = []
    for line in output.splitlines():
        m = re.match(r"^card \d+: (\S+) (\[[^\]]+\])", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            cards.append({"id": m.group(1), "label": f"{m.group(1)} {m.group(2)}"})
    return cards


def build_filter_chain(config):
    filters = []
    if config.get("highpass_enabled"):
        filters.append(f"highpass=f={config['highpass_freq']}")
    gain = float(config.get("gain", 1.0))
    if gain != 1.0:
        filters.append(f"volume={gain}")
    return ",".join(filters) if filters else None


def build_execstart(config):
    alsa_device = f"plughw:CARD={config['card_name']},DEV=0"
    filter_chain = build_filter_chain(config)
    af_part = f' -af "{filter_chain}"' if filter_chain else ""
    rtbufsize = LATENCY_MODES.get(config.get("latency_mode", "balanced"))
    rtbufsize_part = f" -rtbufsize {rtbufsize}" if rtbufsize else ""
    return (
        f"/usr/bin/ffmpeg -f alsa -ar {config['sample_rate']} -ac 1"
        f"{rtbufsize_part} -use_wallclock_as_timestamps 1 -i {alsa_device}{af_part} "
        f"-acodec pcm_s16be -f rtsp rtsp://localhost:{RTSP_PORT}/{STREAM_PATH}"
    )


def write_audio_service(config):
    user_name = getpass.getuser()
    execstart = build_execstart(config)
    content = f"""[Unit]
Description=Audio RTSP Publisher
After=mediamtx.service sound.target
Requires=mediamtx.service
StartLimitIntervalSec=120
StartLimitBurst=10

[Service]
ExecStartPre=/bin/sleep 10
ExecStart={execstart}
Restart=always
RestartSec=5
User={user_name}

[Install]
WantedBy=multi-user.target
"""
    subprocess.run(["sudo", "tee", AUDIO_SERVICE_PATH], input=content, text=True,
                    stdout=subprocess.DEVNULL, check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)


def get_audio_stream_state():
    """Returns 'active', 'inactive', 'failed', or another systemd ActiveState
    value (e.g. 'activating') - distinguishes a clean stop from a crash loop,
    unlike a plain is-active check."""
    result = subprocess.run(["systemctl", "is-active", "audio-rtsp"], capture_output=True, text=True)
    return result.stdout.strip()


def is_audio_stream_active():
    return get_audio_stream_state() == "active"


def start_audio_stream():
    subprocess.run(["sudo", "systemctl", "start", "audio-rtsp"], check=True)


def stop_audio_stream():
    subprocess.run(["sudo", "systemctl", "stop", "audio-rtsp"], check=True)


def restart_audio_stream():
    subprocess.run(["sudo", "systemctl", "restart", "audio-rtsp"], check=True)


def get_cpu_temp_celsius():
    try:
        millidegrees = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip())
        return round(millidegrees / 1000, 1)
    except (FileNotFoundError, ValueError):
        return None


def _format_duration(seconds):
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def get_uptime_string():
    """Device (system) uptime - not shown on the control panel (which shows
    stream uptime instead, see get_stream_uptime_string), kept here in case
    it's useful elsewhere."""
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (FileNotFoundError, ValueError, IndexError):
        return None
    return _format_duration(int(seconds))


def get_stream_uptime_string():
    """How long audio-rtsp.service has been continuously active, using
    systemd's monotonic timestamp (usec since boot) rather than its
    wall-clock one, to avoid unreliable timezone-abbreviation parsing."""
    result = subprocess.run(
        ["systemctl", "show", "audio-rtsp", "-p", "ActiveEnterTimestampMonotonic", "--value"],
        capture_output=True, text=True, check=False,
    )
    try:
        active_since_usec = int(result.stdout.strip())
        now_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (ValueError, FileNotFoundError, IndexError):
        return None
    if active_since_usec <= 0:
        return None
    elapsed = now_seconds - (active_since_usec / 1_000_000)
    if elapsed < 0:
        return None
    return _format_duration(int(elapsed))


def get_cpu_usage_percent(sample_interval=0.2):
    """Instantaneous CPU usage %, computed from the delta between two
    /proc/stat samples taken sample_interval apart (there's no single-point
    "current CPU usage" value in Linux - it's always a rate over some window)."""
    def read_cpu_times():
        line = Path("/proc/stat").read_text().splitlines()[0]
        return [int(x) for x in line.split()[1:]]

    try:
        t1 = read_cpu_times()
        time.sleep(sample_interval)
        t2 = read_cpu_times()
    except (FileNotFoundError, ValueError, IndexError):
        return None

    idle1, idle2 = t1[3] + t1[4], t2[3] + t2[4]
    total_delta = sum(t2) - sum(t1)
    if total_delta <= 0:
        return None
    return round((1 - (idle2 - idle1) / total_delta) * 100, 1)


def get_mediamtx_status():
    """Queries MediaMTX's local API (unauthenticated from 127.0.0.1 by
    default) for the "mic" path's live state - whether it's actually
    publishing, how many RTSP clients are connected, and the real
    negotiated sample rate/channels (a good cross-check that a settings
    change actually took effect). Requires `api: yes` in mediamtx.yml
    (set by install.py) - returns None if the API isn't reachable."""
    try:
        with urllib.request.urlopen(f"{MEDIAMTX_API_BASE}/v3/paths/get/{STREAM_PATH}", timeout=2) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    track_info = (data.get("tracks2") or [{}])[0].get("codecProps", {})
    return {
        "ready": data.get("ready", False),
        "readers": len(data.get("readers", [])),
        "sample_rate": track_info.get("sampleRate"),
        "channels": track_info.get("channelCount"),
    }


def fetch_repo_file(dest, filename, script_dir=None):
    """Copy filename from a local checkout (script_dir) if present, else
    download it from this repo's own GitHub mirror. Used both by install.py
    (initial setup) and webui.py (self-update) - install.py can't rely on
    importing this for the very first fetch of this file itself, so it
    keeps its own minimal bootstrap copy of this logic for that one case.

    Uses the GitHub Contents API rather than raw.githubusercontent.com:
    confirmed in practice that the raw CDN caches for up to 5 minutes and
    completely ignores both cache-busting query params and no-cache request
    headers (a plain client can't force it to revalidate), which can
    silently serve stale/older code right after a push with no error at
    all. The Contents API caches for only ~60s and reflects a fresh push
    correctly - not a perfect fix, but a much smaller staleness window."""
    if script_dir and (Path(script_dir) / filename).is_file():
        dest.write_bytes((Path(script_dir) / filename).read_bytes())
    else:
        req = urllib.request.Request(
            f"{GITHUB_API_CONTENTS_BASE}/{filename}",
            headers={"Accept": "application/vnd.github.raw"},
        )
        with urllib.request.urlopen(req) as resp:
            dest.write_bytes(resp.read())
