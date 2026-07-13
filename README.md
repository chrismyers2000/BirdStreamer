```
============================================
||             BIRD STREAMER              ||
============================================
```

## What is Bird Streamer?

BirdStreamer turns a Raspberry Pi into a headless USB-microphone-to-RTSP audio streamer for Birdnet-go or Birdnetpi. Plug a USB mic into a Pi, run the installer, and it publishes a live RTSP audio stream you can point at [BirdNet-Go](https://github.com/tphakala/birdnet-go) or [BirdNET-Pi](https://github.com/mcguirepr89/BirdNET-Pi) (or anything else that can consume RTSP) for bird sound identification.

It uses [MediaMTX](https://github.com/bluenviron/mediamtx) as the RTSP server and `ffmpeg` to capture and publish the mic audio, both run as systemd services so the stream comes back up automatically on boot or after a crash. A small local web control panel lets you change audio settings afterward without needing to SSH back in.

## Supported hardware

Any single-core Raspberry Pi automatically fails — its CPU can't reliably keep up with `ffmpeg` + MediaMTX running at once (confirmed via testing on a Zero W: pegged at 100% CPU, intermittent stream).

| Model | CPU | Status |
|---|---|---|
| Pi Pico / Pico W / Pico 2 / Pico 2 W | Microcontroller (RP2040/RP2350) | ❌ Not applicable — doesn't run Linux/systemd |
| Pi 1 Model A / A+ / B / B+ | Single-core ARMv6 | ❌ Not supported (single-core) |
| Compute Module 1 (CM1) | Single-core ARMv6 | ❌ Not supported (single-core) |
| Pi Zero (original) | Single-core ARMv6 | ❌ Not supported (No Wifi) |
| Pi Zero W | Single-core ARMv6 | ❌ Not supported (single-core) — Tested and failed,  CPU  at 100%, stream cuts out. |
| Pi 2 Model B | Quad-core ARMv7 | Should work (untested) |
| Pi 3 Model B / B+ / A+ | Quad-core ARMv8 | Should work (untested) |
| Compute Module 3 / 3+ (CM3/CM3+) | Quad-core ARMv8 | Should work (untested) |
| **Pi Zero 2 W** | Quad-core ARMv8 | ✅ Tested and working |
| **Pi 4 Model B** | Quad-core ARMv8 (Cortex-A72) | ✅ Tested and working |
| Pi 400 | Quad-core ARMv8 (Cortex-A72) | Should work (untested — same SoC as Pi 4B) |
| Compute Module 4 (CM4) | Quad-core ARMv8 (Cortex-A72) | Should work (untested) |
| Pi 5 | Quad-core ARMv8 (Cortex-A76) | Should work (untested) |
| Compute Module 5 (CM5) | Quad-core ARMv8 (Cortex-A76) | Should work (untested) |
| Pi 500 | Quad-core ARMv8 (Cortex-A76) | Should work (untested — same SoC as Pi 5) |


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
