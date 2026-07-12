```
============================================
||             BIRD STREAMER              ||
============================================
```

## What is Bird Streamer?

BirdStreamer turns a Raspberry Pi into a headless USB-microphone-to-RTSP audio streamer for Birdnet-go or Birdnetpi. Plug a USB mic into a Pi, run the installer, and it publishes a live RTSP audio stream you can point at [BirdNet-Go](https://github.com/tphakala/birdnet-go) or [BirdNET-Pi](https://github.com/mcguirepr89/BirdNET-Pi) (or anything else that can consume RTSP) for bird sound identification.

It uses [MediaMTX](https://github.com/bluenviron/mediamtx) as the RTSP server and `ffmpeg` to capture and publish the mic audio, both run as systemd services so the stream comes back up automatically on boot or after a crash. A small local web control panel lets you change audio settings afterward without needing to SSH back in.

**Supported hardware:** any Raspberry Pi newer and faster than  the Raspberry Pi Zero 2 W**, but **not** the original (single-core) Raspberry Pi Zero W. That board's CPU can't reliably keep up with `ffmpeg` + MediaMTX running at once (confirmed via testing: pegged at 100% CPU, intermittent stream), so the installer detects and refuses to run on it rather than leave you with a flaky setup.

## How to use it

**Single-line install** (the recommended way — run this on the Pi itself, over SSH or a direct terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/chrismyers2000/BirdStreamer/main/install.py | python3
```

It will detect your USB mic (prompting you to pick one if more than one is plugged in), download MediaMTX, and set everything up. At the end it prints your stream URL and the control panel URL, e.g.:

```
Stream URL:       rtsp://<pi-ip>:8554/mic
Control panel:    http://<pi-ip>:8080
```

**Uninstalling** reverses everything the installer set up (services, the web control panel, the hardware watchdog config) and leaves shared system packages (`ffmpeg`, `alsa-utils`, etc.) alone:

```bash
curl -fsSL https://raw.githubusercontent.com/chrismyers2000/BirdStreamer/main/uninstall.py | python3
```

## Features & changing settings

Everything below is controlled from the web control panel at `http://<pi-ip>:8080` — no SSH needed after the initial install.

- **Stream on/off** — a button toggles the RTSP publisher on or off, with a status indicator showing whether it's currently running. (The underlying MediaMTX server itself stays up regardless, ready to accept a connection whenever the stream is turned back on.)
- **Sound card selection** — pick which detected USB microphone to capture from, if you have more than one connected. The list re-scans hardware every time you load the page, so a newly plugged-in mic shows up on your next reload.
- **Sample rate** — choose from common rates (8000 / 16000 / 22050 / 44100 / 48000 Hz).
- **Gain** — a slider to boost or reduce the mic's volume (0.5x–4x).
- **High-pass filter** — an optional filter with an adjustable cutoff frequency (20–1000 Hz), useful for cutting outdoor wind and low-frequency rumble noise that sits below where most bird vocalizations start.

Saving settings rewrites the audio service's configuration and restarts it automatically, so changes take effect within a few seconds — no reboot required.
