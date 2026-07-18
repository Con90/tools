#!/usr/bin/env bash
#
# run.sh — one-click launcher for pubmed_scraper.py
#
# First run: creates a local virtual environment (.venv) and installs the
# dependencies. Every run after that just activates it and runs the tool.
# Any arguments you pass are forwarded to the scraper, e.g.:
#     ./run.sh --search proteomics --days 14
#
set -euo pipefail

# Work from the folder this script lives in, so double-clicking works
# regardless of the current directory.
cd "$(dirname "$0")"

VENV=".venv"

# Create the virtual environment on first run.
if [ ! -d "$VENV" ]; then
    echo "First run: setting up virtual environment in $VENV ..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r requirements.txt
    echo "Setup complete."
fi

# Run the scraper using the venv's Python, forwarding any arguments.
"$VENV/bin/python" pubmed_scraper.py "$@"

echo
echo "Done. Results are in the 'output' folder."

# Keep the window open if the script was double-clicked from a file manager
# (i.e. not launched from an interactive terminal).
if [ ! -t 0 ]; then
    read -r -p "Press Enter to close..."
fi
