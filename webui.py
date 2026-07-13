#!/usr/bin/env python3
# BirdStreamer local control panel - lets you change the sound card, sample
# rate, gain, and high-pass filter without SSH, and toggle the RTSP stream
# on/off. Runs as its own systemd service (birdstreamer-webui.service),
# always on regardless of whether the audio stream itself is toggled.
#
# This imports birdstreamer_common.py, which must live in the same directory
# (both are deployed together by install.py to ~/.birdstreamer/app/).

import sys
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
  }
  html.light {
    --bg: #ffffff; --fg: #212529; --card-bg: #f8f9fa; --border: #ccc;
    --on-bg: #d4edda; --on-fg: #155724; --off-bg: #f8d7da; --off-fg: #721c24;
  }
  body { font-family: sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; background: var(--bg); color: var(--fg); }
  h1 { text-align: center; }
  .topbar { display: flex; justify-content: flex-end; }
  .theme-toggle { width: auto; margin: 0; padding: 0.4rem 0.8rem; background: var(--card-bg); color: var(--fg); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; }
  .status { text-align: center; font-weight: bold; padding: 0.5rem; border-radius: 6px; margin-bottom: 1rem; }
  .on { background: var(--on-bg); color: var(--on-fg); }
  .off { background: var(--off-bg); color: var(--off-fg); }
  form { margin-bottom: 1.5rem; }
  label { display: block; margin-top: 0.75rem; }
  select, input[type=number] { width: 100%; padding: 0.25rem; background: var(--card-bg); color: var(--fg); border: 1px solid var(--border); }
  input[type=range] { width: 100%; }
  button { margin-top: 1rem; width: 100%; padding: 0.5rem; }
</style>
</head>
<body>
  <div class="topbar">
    <button type="button" class="theme-toggle" id="themeToggle" onclick="toggleTheme()"></button>
  </div>
  <h1>BirdStreamer</h1>
  <div class="status {{ 'on' if active else 'off' }}">Stream is {{ 'ON' if active else 'OFF' }}</div>

  <form method="post" action="{{ url_for('toggle') }}">
    <button type="submit">{{ 'Turn Stream Off' if active else 'Turn Stream On' }}</button>
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
      <input type="range" name="gain" min="0.5" max="4" step="0.1" value="{{ config.gain }}"
             oninput="document.getElementById('gainValue').textContent = this.value">
    </label>

    <label>
      <input type="checkbox" name="highpass_enabled" {{ 'checked' if config.highpass_enabled else '' }}>
      Enable high-pass filter (cuts wind/rumble noise below this frequency)
    </label>
    <label>High-pass frequency (Hz)
      <input type="number" name="highpass_freq" min="20" max="1000" value="{{ config.highpass_freq }}">
    </label>

    <button type="submit">Save Settings &amp; Restart Stream</button>
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


@app.route("/")
def index():
    config = common.load_config()
    cards = common.detect_cards()
    if config["card_name"] is None and cards:
        config["card_name"] = cards[0]["id"]
    return render_template_string(
        PAGE,
        config=config,
        cards=cards,
        rates=common.SAMPLE_RATES,
        active=common.is_audio_stream_active(),
    )


@app.route("/toggle", methods=["POST"])
def toggle():
    if common.is_audio_stream_active():
        common.stop_audio_stream()
    else:
        common.start_audio_stream()
    return redirect(url_for("index"))


@app.route("/settings", methods=["POST"])
def settings():
    config = common.load_config()
    config["card_name"] = request.form["card_name"]
    config["sample_rate"] = int(request.form["sample_rate"])
    config["gain"] = float(request.form["gain"])
    config["highpass_enabled"] = "highpass_enabled" in request.form
    config["highpass_freq"] = int(request.form["highpass_freq"])
    common.save_config(config)
    common.write_audio_service(config)
    common.restart_audio_stream()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
