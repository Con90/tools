#!/usr/bin/env bash
#
# run.sh — one-click launcher for pubmed_scraper.py
#
# Double-click it (choose "Run in Terminal") or run ./run.sh with no arguments
# and it asks what to search for. Any arguments are passed straight to the
# scraper instead, for scripted or scheduled use, e.g.:
#     ./run.sh --search proteomics --days 14
#
# The first run creates a local virtual environment (.venv) and installs the
# dependencies; later runs reuse it.
#
set -euo pipefail

# Work from the folder this script lives in, so double-clicking works
# regardless of the current directory.
cd "$(dirname "$0")"

VENV=".venv"

pause() {
    echo
    read -r -p "Press Enter to close..." _ || true
}

# (Re)build the virtual environment if it's missing or incomplete, e.g. after
# a first run that was interrupted.
if ! "$VENV/bin/python" -c "import requests, yaml" 2>/dev/null; then
    echo "Setting up the Python environment (first run only)..."
    rm -rf "$VENV"
    if ! python3 -m venv "$VENV"; then
        rm -rf "$VENV"
        echo "Couldn't create a virtual environment."
        echo "On Debian/Ubuntu, install support for it with:  sudo apt install python3-venv"
        [ $# -eq 0 ] && pause
        exit 1
    fi
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r requirements.txt
    echo "Setup complete."
fi

if [ $# -eq 0 ]; then
    # No arguments (e.g. double-clicked): ask for the search interactively and
    # keep the window open afterwards so the results can be read.
    status=0
    "$VENV/bin/python" pubmed_scraper.py --interactive || status=$?
    pause
    exit "$status"
fi

"$VENV/bin/python" pubmed_scraper.py "$@"
