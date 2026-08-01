#!/usr/bin/env bash
# Launches the Planner app.
cd "/media/connor/Seagate Barracuda 1TB/ClaudeCode/Apps/Planner" || {
  echo "Planner folder not found (is the drive mounted?)"; read -r -p "Press Enter to close..."; exit 1;
}
exec ./node_modules/.bin/electron .
