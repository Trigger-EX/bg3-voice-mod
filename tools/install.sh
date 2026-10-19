#!/usr/bin/env bash
# Linux Mint / Ubuntu setup for BG3 Voice Forge.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip ffmpeg libxcb-cursor0 git
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e '.[dev]'
echo "Run with: .venv/bin/bg3vm"
