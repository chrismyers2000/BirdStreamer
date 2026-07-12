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
import subprocess
from pathlib import Path

APP_DIR = Path.home() / ".birdstreamer"
CONFIG_PATH = APP_DIR / "config.json"
AUDIO_SERVICE_PATH = "/etc/systemd/system/audio-rtsp.service"
RTSP_PORT = 8554
STREAM_PATH = "mic"
SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000]

DEFAULT_CONFIG = {
    "card_name": None,
    "sample_rate": 48000,
    "gain": 1.0,
    "highpass_enabled": False,
    "highpass_freq": 100,
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
    return (
        f"/usr/bin/ffmpeg -f alsa -ar {config['sample_rate']} -ac 1 "
        f"-use_wallclock_as_timestamps 1 -i {alsa_device}{af_part} "
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


def is_audio_stream_active():
    result = subprocess.run(["systemctl", "is-active", "audio-rtsp"], capture_output=True, text=True)
    return result.stdout.strip() == "active"


def start_audio_stream():
    subprocess.run(["sudo", "systemctl", "start", "audio-rtsp"], check=True)


def stop_audio_stream():
    subprocess.run(["sudo", "systemctl", "stop", "audio-rtsp"], check=True)


def restart_audio_stream():
    subprocess.run(["sudo", "systemctl", "restart", "audio-rtsp"], check=True)
