#!/usr/bin/env bash
#
# run.sh — one-click launcher for bike_fit.py
#
# First run: creates a local virtual environment (.venv) and installs the
# dependencies. Every run after that just activates it and runs the tool.
# Any arguments you pass are forwarded, e.g.:
#     ./run.sh analyze ride.mp4 --leg-mm 880
#     ./run.sh demo
#
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"

if [ ! -d "$VENV" ]; then
    echo "First run: setting up virtual environment in $VENV ..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r requirements.txt
    echo "Setup complete."
fi

if [ $# -eq 0 ]; then
    "$VENV/bin/python" bike_fit.py --help
else
    "$VENV/bin/python" bike_fit.py "$@"
fi
