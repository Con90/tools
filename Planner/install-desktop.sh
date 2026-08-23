#!/usr/bin/env bash
#
# install-desktop.sh — installs the Planner icon and launcher for the current
# user, so the desktop shortcut, the applications menu and the running window's
# panel/taskbar entry all show the same icon.
#
# Safe to re-run (e.g. after regenerating the icon with build-icon.py).
set -euo pipefail

cd "$(dirname "$0")"
APPDIR="$PWD"
ICONS="$HOME/.local/share/icons/hicolor"
APPS="$HOME/.local/share/applications"

# 1. Icon into the hicolor theme under the name "planner".
#    The name matches the window's WM_CLASS, so the panel finds it too.
for size in 32 64 128 256; do
    install -Dm644 "build/icon-$size.png" "$ICONS/${size}x${size}/apps/planner.png"
done
install -Dm644 "build/icon.png" "$ICONS/512x512/apps/planner.png"

# 2. Launcher, with Exec pointing at this folder wherever it lives.
mkdir -p "$APPS"
sed "s|^Exec=.*|Exec=\"$APPDIR/run-planner.sh\"|" Planner.desktop > "$APPS/Planner.desktop"
chmod +x "$APPS/Planner.desktop"

# 3. Same launcher on the Desktop, marked trusted for Nemo/Nautilus.
if [ -d "$HOME/Desktop" ]; then
    cp "$APPS/Planner.desktop" "$HOME/Desktop/Planner.desktop"
    chmod +x "$HOME/Desktop/Planner.desktop"
    gio set "$HOME/Desktop/Planner.desktop" metadata::trusted true 2>/dev/null || true
fi

# 4. Refresh caches so the new icon shows up without a re-login.
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -qtf "$ICONS" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true

echo "Installed. Icon: $ICONS/<size>/apps/planner.png"
echo "Launchers: $APPS/Planner.desktop and ~/Desktop/Planner.desktop"
