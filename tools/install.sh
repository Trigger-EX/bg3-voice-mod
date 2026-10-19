#!/usr/bin/env bash
# Optional: system packages. Python dependencies (PySide6 etc.) are installed automatically
# into an app-local venv the first time you run ./bg3-voice-forge.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip ffmpeg libxcb-cursor0 git
echo "Now run: ./bg3-voice-forge"
