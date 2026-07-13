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
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import birdstreamer_common as common  # noqa: E402

from flask import Flask, render_template_string, request, redirect, url_for  # noqa: E402

app = Flask(__name__)

PAGE = """<!doctype html>
<html>
<head>
<title>BirdStreamer Control Panel</title>
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
</style>
</head>
<body>
  <div class="topbar">
    <button type="button" class="theme-toggle" id="themeToggle" onclick="toggleTheme()"></button>
  </div>
  <h1>BirdStreamer</h1>

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

  <form method="post" action="{{ url_for('toggle') }}">
    <button type="submit">{{ 'Turn Stream Off' if stream_state == 'active' else 'Turn Stream On' }}</button>
  </form>

  <form method="post" action="{{ url_for('settings') }}">
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
    return render_template_string(
        PAGE,
        config=config,
        cards=cards,
        rates=common.SAMPLE_RATES,
        gain_min=common.GAIN_MIN,
        gain_max=common.GAIN_MAX,
        highpass_min=common.HIGHPASS_FREQ_MIN,
        highpass_max=common.HIGHPASS_FREQ_MAX,
        stream_state=common.get_audio_stream_state(),
        cpu_temp=common.get_cpu_temp_celsius(),
        cpu_usage=common.get_cpu_usage_percent(),
        stream_uptime=common.get_stream_uptime_string(),
        mediamtx=common.get_mediamtx_status(),
        errors=errors or [],
    )


def validate_settings(form, cards):
    errors = []
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

    if errors:
        return None, errors
    return {
        "card_name": card_name,
        "sample_rate": sample_rate,
        "gain": gain,
        "highpass_enabled": highpass_enabled,
        "highpass_freq": highpass_freq,
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


def _delayed_reexec():
    time.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@app.route("/update", methods=["POST"])
def update():
    app_dir = Path(__file__).resolve().parent
    try:
        common.fetch_repo_file(app_dir / "birdstreamer_common.py", "birdstreamer_common.py")
        common.fetch_repo_file(app_dir / "webui.py", "webui.py")
    except OSError as e:
        return render_index(errors=[f"Update failed (could not reach GitHub): {e}"]), 502
    threading.Thread(target=_delayed_reexec, daemon=True).start()
    return UPDATE_PAGE


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
