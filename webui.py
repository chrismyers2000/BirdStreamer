#!/usr/bin/env python3
# BirdStreamer local control panel - lets you change the sound card, sample
# rate, gain, and high-pass filter without SSH, toggle the RTSP stream
# on/off, see live status, and self-update. Runs as its own systemd service
# (birdstreamer-webui.service), always on regardless of whether the audio
# stream itself is toggled.
#
# This imports birdstreamer_common.py, which must live in the same directory
# (both are deployed together by install.py to ~/.birdstreamer/, and both
# are refetched together by the self-update button below).

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import birdstreamer_common as common  # noqa: E402

from flask import Flask, render_template_string, request, redirect, url_for, send_file, abort  # noqa: E402

app = Flask(__name__)

PAGE = """<!doctype html>
<html>
<head>
<title>{{ config.device_name }} Control Panel</title>
<script>
  // Applied before body renders, to avoid a flash of the wrong theme.
  (function() {
    if ((localStorage.getItem('theme') || 'dark') === 'light') {
      document.documentElement.classList.add('light');
    }
  })();
</script>
<style>
  :root {
    --bg: #121212; --fg: #e0e0e0; --card-bg: #1e1e1e; --border: #3a3a3a;
    --on-bg: #1e4620; --on-fg: #8fd19e; --off-bg: #4a1c1f; --off-fg: #f5a3a8;
    --failing-bg: #4a3a1c; --failing-fg: #f5d391; --error-bg: #4a1c1f; --error-fg: #f5a3a8;
  }
  html.light {
    --bg: #ffffff; --fg: #212529; --card-bg: #f8f9fa; --border: #ccc;
    --on-bg: #d4edda; --on-fg: #155724; --off-bg: #f8d7da; --off-fg: #721c24;
    --failing-bg: #fff3cd; --failing-fg: #856404; --error-bg: #f8d7da; --error-fg: #721c24;
  }
  body { font-family: sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; background: var(--bg); color: var(--fg); }
  h1 { text-align: center; }
  .topbar { display: flex; justify-content: flex-end; }
  .theme-toggle { width: auto; margin: 0; padding: 0.4rem 0.8rem; background: var(--card-bg); color: var(--fg); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; }
  .status { text-align: center; font-weight: bold; padding: 0.5rem; border-radius: 6px; margin-bottom: 1rem; }
  .on { background: var(--on-bg); color: var(--on-fg); }
  .off { background: var(--off-bg); color: var(--off-fg); }
  .failing { background: var(--failing-bg); color: var(--failing-fg); }
  .errors { background: var(--error-bg); color: var(--error-fg); padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; }
  .errors ul { margin: 0; padding-left: 1.2rem; }
  .statgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 0.75rem; margin-bottom: 1.5rem; font-size: 0.9rem; }
  .statgrid div span { display: block; color: var(--fg); opacity: 0.7; font-size: 0.8rem; }
  form { margin-bottom: 1.5rem; }
  label { display: block; margin-top: 0.75rem; }
  select, input[type=number] { width: 100%; padding: 0.25rem; background: var(--card-bg); color: var(--fg); border: 1px solid var(--border); }
  input[type=range] { width: 100%; }
  button { margin-top: 1rem; width: 100%; padding: 0.5rem; }
  .secondary { background: var(--card-bg); color: var(--fg); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; }
  .listen-live { margin-bottom: 1.5rem; }
  .listen-live iframe { width: 100%; height: 100px; border: 1px solid var(--border); border-radius: 6px; }
  .listen-live a { display: block; text-align: center; font-size: 0.85rem; margin-top: 0.3rem; color: var(--fg); opacity: 0.7; }
  .section-title { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.6; margin: 1.5rem 0 0.25rem; border-bottom: 1px solid var(--border); padding-bottom: 0.25rem; }
  .section-title:first-child { margin-top: 0; }
  details { margin-top: 1rem; border: 1px solid var(--border); border-radius: 6px; padding: 0.5rem 0.75rem; }
  details summary { cursor: pointer; font-size: 0.9rem; opacity: 0.8; }
  details[open] summary { margin-bottom: 0.5rem; }
  .self-test audio { width: 100%; margin-top: 0.5rem; }
  .hint { font-size: 0.8rem; opacity: 0.6; margin: 0.2rem 0 0; }
</style>
</head>
<body>
  <div class="topbar">
    <button type="button" class="theme-toggle" id="themeToggle" onclick="toggleTheme()"></button>
  </div>
  <h1>{{ config.device_name }}</h1>

  {% if errors %}
  <div class="errors">
    <strong>Couldn't save settings:</strong>
    <ul>{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
  </div>
  {% endif %}

  <div class="status {{ 'on' if stream_state == 'active' else ('failing' if stream_state == 'failed' else 'off') }}">
    Stream is {{ 'ON' if stream_state == 'active' else ('FAILING' if stream_state == 'failed' else 'OFF') }}
  </div>

  <div class="statgrid">
    <div><span>CPU temp</span>{{ cpu_temp ~ '°C' if cpu_temp is not none else 'n/a' }}</div>
    <div><span>CPU usage</span>{{ cpu_usage ~ '%' if cpu_usage is not none else 'n/a' }}</div>
    <div><span>Stream uptime</span>{{ stream_uptime or 'n/a' }}</div>
    <div><span>Viewers</span>{{ mediamtx.readers if mediamtx else 'n/a' }}</div>
    <div><span>Live format</span>{{ (mediamtx.sample_rate ~ ' Hz / ' ~ mediamtx.channels ~ 'ch') if mediamtx and mediamtx.ready else 'n/a' }}</div>
  </div>

  {% if stream_state == 'active' %}
  <div class="listen-live">
    <iframe src="http://{{ webrtc_host }}:8889/{{ stream_path }}/?muted=false&controls=true" allow="autoplay"></iframe>
    <a href="http://{{ webrtc_host }}:8889/{{ stream_path }}/?muted=false&controls=true" target="_blank">Open in new tab &#8599;</a>
  </div>
  {% endif %}

  <form method="post" action="{{ url_for('toggle') }}">
    <button type="submit">{{ 'Turn Stream Off' if stream_state == 'active' else 'Turn Stream On' }}</button>
  </form>

  <form method="post" action="{{ url_for('self_test') }}" class="self-test">
    <button type="submit" class="secondary">Record {{ self_test_seconds }}s Test Clip</button>
    {% if self_test_clip_mtime %}
    <audio controls src="{{ url_for('self_test_clip') }}?t={{ self_test_clip_mtime }}"></audio>
    {% endif %}
  </form>

  <form method="post" action="{{ url_for('settings') }}">
    <h2 class="section-title">Device</h2>
    <label>Device name
      <input type="text" name="device_name" maxlength="{{ device_name_max_len }}" value="{{ config.device_name }}">
    </label>

    <h2 class="section-title">Input</h2>
    <label>Sound card
      <select name="card_name">
        {% for c in cards %}
        <option value="{{ c.id }}" {{ 'selected' if c.id == config.card_name else '' }}>{{ c.label }}</option>
        {% endfor %}
      </select>
    </label>
    <label>Sample rate
      <select name="sample_rate">
        {% for r in rates %}
        <option value="{{ r }}" {{ 'selected' if r == config.sample_rate else '' }}>{{ r }} Hz</option>
        {% endfor %}
      </select>
    </label>

    <h2 class="section-title">Audio Processing</h2>
    <label>Gain (<span id="gainValue">{{ config.gain }}</span>x)
      <input type="range" name="gain" min="{{ gain_min }}" max="{{ gain_max }}" step="0.1" value="{{ config.gain }}"
             oninput="document.getElementById('gainValue').textContent = this.value">
    </label>

    <label>
      <input type="checkbox" name="highpass_enabled" {{ 'checked' if config.highpass_enabled else '' }}>
      Enable high-pass filter (cuts wind/rumble noise below this frequency)
    </label>
    <label>High-pass frequency (Hz)
      <input type="number" name="highpass_freq" min="{{ highpass_min }}" max="{{ highpass_max }}" value="{{ config.highpass_freq }}">
    </label>

    <label>
      <input type="checkbox" name="noise_gate_enabled" {{ 'checked' if config.noise_gate_enabled else '' }}>
      Enable noise gate (mutes audio quieter than this threshold)
    </label>
    <label>Noise gate threshold (<span id="noiseGateValue">{{ config.noise_gate_threshold_db }}</span> dB)
      <input type="range" name="noise_gate_threshold_db" min="{{ noise_gate_db_min }}" max="{{ noise_gate_db_max }}" step="1" value="{{ config.noise_gate_threshold_db }}"
             oninput="document.getElementById('noiseGateValue').textContent = this.value">
    </label>

    <details>
      <summary>Advanced</summary>

      {% if hw_gain_available %}
      <label>
        <input type="checkbox" name="hw_gain_enabled" {{ 'checked' if config.hw_gain_enabled else '' }}>
        Enable hardware input gain (adjusts the mic's own capture level, cleaner than software gain alone)
      </label>
      <label>Hardware gain (<span id="hwGainValue">{{ config.hw_gain_percent }}</span>%)
        <input type="range" name="hw_gain_percent" min="{{ hw_gain_min }}" max="{{ hw_gain_max }}" step="1" value="{{ config.hw_gain_percent }}"
               oninput="document.getElementById('hwGainValue').textContent = this.value">
      </label>
      {% else %}
      <p class="hint">No adjustable hardware gain control detected for this sound card.</p>
      {% endif %}

      <label>Capture buffer
        <select name="latency_mode">
          <option value="low" {{ 'selected' if config.latency_mode == 'low' else '' }}>Low latency (less resilient to hiccups)</option>
          <option value="balanced" {{ 'selected' if config.latency_mode == 'balanced' else '' }}>Balanced (default)</option>
          <option value="high_stability" {{ 'selected' if config.latency_mode == 'high_stability' else '' }}>High stability (more latency)</option>
        </select>
      </label>
    </details>

    <button type="submit">Save Settings &amp; Restart Stream</button>
  </form>

  <form method="post" action="{{ url_for('update') }}" onsubmit="return confirm('Update BirdStreamer to the latest version from GitHub and restart the control panel?');">
    <button type="submit" class="secondary">Check for Updates</button>
  </form>

<script>
  function currentTheme() { return localStorage.getItem('theme') || 'dark'; }
  function updateToggleLabel() {
    document.getElementById('themeToggle').textContent = currentTheme() === 'light' ? '\\u{1F319} Dark' : '\\u{2600} Light';
  }
  function toggleTheme() {
    var next = currentTheme() === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', next);
    document.documentElement.classList.toggle('light', next === 'light');
    updateToggleLabel();
  }
  updateToggleLabel();
</script>
</body>
</html>
"""

UPDATE_PAGE = """<!doctype html>
<html>
<head>
<title>Updating BirdStreamer...</title>
<meta http-equiv="refresh" content="6;url=/">
<style>
  body { font-family: sans-serif; max-width: 480px; margin: 4rem auto; text-align: center; }
</style>
</head>
<body>
  <h1>Updating...</h1>
  <p>Fetched the latest version and restarting the control panel. This page will reload automatically in a few seconds.</p>
</body>
</html>
"""


def render_index(errors=None):
    config = common.load_config()
    cards = common.detect_cards()
    if config["card_name"] is None and cards:
        config["card_name"] = cards[0]["id"]
    hw_gain_available = bool(config["card_name"] and common.get_primary_capture_control(config["card_name"]))
    clip_mtime = int(common.SELF_TEST_CLIP_PATH.stat().st_mtime) if common.SELF_TEST_CLIP_PATH.exists() else None
    return render_template_string(
        PAGE,
        config=config,
        cards=cards,
        rates=common.SAMPLE_RATES,
        gain_min=common.GAIN_MIN,
        gain_max=common.GAIN_MAX,
        highpass_min=common.HIGHPASS_FREQ_MIN,
        highpass_max=common.HIGHPASS_FREQ_MAX,
        noise_gate_db_min=common.NOISE_GATE_DB_MIN,
        noise_gate_db_max=common.NOISE_GATE_DB_MAX,
        hw_gain_min=common.HW_GAIN_MIN,
        hw_gain_max=common.HW_GAIN_MAX,
        hw_gain_available=hw_gain_available,
        device_name_max_len=common.DEVICE_NAME_MAX_LEN,
        self_test_seconds=common.SELF_TEST_CLIP_SECONDS,
        self_test_clip_mtime=clip_mtime,
        stream_state=common.get_audio_stream_state(),
        cpu_temp=common.get_cpu_temp_celsius(),
        cpu_usage=common.get_cpu_usage_percent(),
        stream_uptime=common.get_stream_uptime_string(),
        mediamtx=common.get_mediamtx_status(),
        webrtc_host=request.host.split(":")[0],
        stream_path=common.STREAM_PATH,
        errors=errors or [],
    )


def validate_settings(form, cards):
    errors = []

    device_name = form.get("device_name", "").strip()
    if not device_name:
        errors.append("Device name can't be empty")
    elif len(device_name) > common.DEVICE_NAME_MAX_LEN:
        errors.append(f"Device name must be at most {common.DEVICE_NAME_MAX_LEN} characters")

    card_ids = {c["id"] for c in cards}
    card_name = form.get("card_name", "")
    if card_name not in card_ids:
        errors.append(f"Unknown sound card: {card_name!r}")

    sample_rate = None
    try:
        sample_rate = int(form.get("sample_rate", ""))
        if sample_rate not in common.SAMPLE_RATES:
            errors.append(f"Sample rate must be one of {common.SAMPLE_RATES}")
    except ValueError:
        errors.append("Sample rate must be a number")

    gain = None
    try:
        gain = float(form.get("gain", ""))
        if not (common.GAIN_MIN <= gain <= common.GAIN_MAX):
            errors.append(f"Gain must be between {common.GAIN_MIN} and {common.GAIN_MAX}")
    except ValueError:
        errors.append("Gain must be a number")

    highpass_enabled = "highpass_enabled" in form
    highpass_freq = None
    try:
        highpass_freq = int(form.get("highpass_freq", ""))
        if not (common.HIGHPASS_FREQ_MIN <= highpass_freq <= common.HIGHPASS_FREQ_MAX):
            errors.append(f"High-pass frequency must be between {common.HIGHPASS_FREQ_MIN} and {common.HIGHPASS_FREQ_MAX} Hz")
    except ValueError:
        errors.append("High-pass frequency must be a number")

    noise_gate_enabled = "noise_gate_enabled" in form
    noise_gate_threshold_db = None
    try:
        noise_gate_threshold_db = int(form.get("noise_gate_threshold_db", ""))
        if not (common.NOISE_GATE_DB_MIN <= noise_gate_threshold_db <= common.NOISE_GATE_DB_MAX):
            errors.append(f"Noise gate threshold must be between {common.NOISE_GATE_DB_MIN} and {common.NOISE_GATE_DB_MAX} dB")
    except ValueError:
        errors.append("Noise gate threshold must be a number")

    # hw_gain_percent only appears in the form when a hardware gain control
    # was actually detected for the current card - absent, not empty, when
    # there's nothing to control. Don't treat that as a validation error.
    hw_gain_enabled = "hw_gain_enabled" in form
    if "hw_gain_percent" in form:
        hw_gain_percent = None
        try:
            hw_gain_percent = int(form.get("hw_gain_percent"))
            if not (common.HW_GAIN_MIN <= hw_gain_percent <= common.HW_GAIN_MAX):
                errors.append(f"Hardware gain must be between {common.HW_GAIN_MIN} and {common.HW_GAIN_MAX}")
        except ValueError:
            errors.append("Hardware gain must be a number")
    else:
        hw_gain_percent = common.DEFAULT_CONFIG["hw_gain_percent"]

    latency_mode = form.get("latency_mode", "")
    if latency_mode not in common.LATENCY_MODES:
        errors.append(f"Invalid capture buffer mode: {latency_mode!r}")

    if errors:
        return None, errors
    return {
        "device_name": device_name,
        "card_name": card_name,
        "sample_rate": sample_rate,
        "gain": gain,
        "highpass_enabled": highpass_enabled,
        "highpass_freq": highpass_freq,
        "noise_gate_enabled": noise_gate_enabled,
        "noise_gate_threshold_db": noise_gate_threshold_db,
        "hw_gain_enabled": hw_gain_enabled,
        "hw_gain_percent": hw_gain_percent,
        "latency_mode": latency_mode,
    }, []


@app.route("/")
def index():
    return render_index()


@app.route("/toggle", methods=["POST"])
def toggle():
    if common.is_audio_stream_active():
        common.stop_audio_stream()
    else:
        common.start_audio_stream()
    return redirect(url_for("index"))


@app.route("/settings", methods=["POST"])
def settings():
    cards = common.detect_cards()
    new_config, errors = validate_settings(request.form, cards)
    if errors:
        return render_index(errors=errors), 400
    common.save_config(new_config)
    common.write_audio_service(new_config)
    common.restart_audio_stream()
    return redirect(url_for("index"))


@app.route("/self_test", methods=["POST"])
def self_test():
    try:
        common.capture_self_test_clip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return render_index(errors=[f"Self-test capture failed: {e}"]), 500
    return redirect(url_for("index"))


@app.route("/self_test_clip")
def self_test_clip():
    if not common.SELF_TEST_CLIP_PATH.exists():
        abort(404)
    return send_file(common.SELF_TEST_CLIP_PATH, mimetype="audio/wav")


def _delayed_reexec():
    time.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


CONFIG_BACKUP_PATH = common.APP_DIR / "config.json.update-backup"


def _restore_config_backup_if_present():
    """Runs at process startup (including right after self-update's re-exec).
    Belt-and-suspenders: the update route backs up config.json before
    fetching new code, in case anything about the fetch/re-exec cycle
    affects it. Always wins over whatever's currently in config.json, since
    it's a snapshot of settings from immediately before the update."""
    if CONFIG_BACKUP_PATH.exists():
        CONFIG_BACKUP_PATH.replace(common.CONFIG_PATH)


@app.route("/update", methods=["POST"])
def update():
    app_dir = Path(__file__).resolve().parent
    if common.CONFIG_PATH.exists():
        CONFIG_BACKUP_PATH.write_text(common.CONFIG_PATH.read_text())
    try:
        common.fetch_repo_file(app_dir / "birdstreamer_common.py", "birdstreamer_common.py")
        common.fetch_repo_file(app_dir / "webui.py", "webui.py")
    except OSError as e:
        return render_index(errors=[f"Update failed (could not reach GitHub): {e}"]), 502
    threading.Thread(target=_delayed_reexec, daemon=True).start()
    return UPDATE_PAGE


_restore_config_backup_if_present()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
