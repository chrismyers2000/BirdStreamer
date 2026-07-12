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
<style>
  body { font-family: sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; }
  h1 { text-align: center; }
  .status { text-align: center; font-weight: bold; padding: 0.5rem; border-radius: 6px; margin-bottom: 1rem; }
  .on { background: #d4edda; color: #155724; }
  .off { background: #f8d7da; color: #721c24; }
  form { margin-bottom: 1.5rem; }
  label { display: block; margin-top: 0.75rem; }
  select, input[type=number] { width: 100%; padding: 0.25rem; }
  input[type=range] { width: 100%; }
  button { margin-top: 1rem; width: 100%; padding: 0.5rem; }
</style>
</head>
<body>
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

    <label>Gain ({{ config.gain }}x)
      <input type="range" name="gain" min="0.5" max="4" step="0.1" value="{{ config.gain }}">
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
