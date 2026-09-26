#!/usr/bin/env bash
#
# run.sh — one-click launcher for Stylist
#
# First run: creates a local virtual environment (.venv) and installs the
# dependencies. Every run after that just starts the app and opens it in your
# browser at http://127.0.0.1:8765. Your data lives in data/stylist.db.
#
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PORT="${STYLIST_PORT:-8765}"
URL="http://127.0.0.1:$PORT"

if [ ! -d "$VENV" ]; then
    echo "First run: setting up virtual environment in $VENV ..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r requirements.txt
    echo "Setup complete."
fi

# Open the browser once the server has had a moment to start.
( sleep 1.5; (xdg-open "$URL" || open "$URL") >/dev/null 2>&1 || true ) &

echo "Stylist running at $URL  (Ctrl+C to stop)"
# Bound to 127.0.0.1 so it's only reachable from this computer.
exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
