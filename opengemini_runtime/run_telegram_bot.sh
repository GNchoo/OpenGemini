#!/usr/bin/env bash
set -euo pipefail
cd /home/fallman/.openclaw/workspace/opengemini_runtime

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

exec python telegram_bot.py
