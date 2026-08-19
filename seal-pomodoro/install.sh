#!/usr/bin/env bash
# Install Seal Pomodoro: icon theme entries, a menu launcher and a desktop icon.
set -euo pipefail

APP_ID="seal-pomodoro"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ICONS="$HERE/icons"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
DESKTOP_FILE="$APPS_DIR/$APP_ID.desktop"

if [ ! -f "$ICONS/$APP_ID-256.png" ]; then
    echo "Rendering icons..."
    ( cd "$HERE" && python3 make_icon.py >/dev/null )
fi

echo "Installing icons..."
for size in 16 22 24 32 48 64 128 256 512; do
    dest="$ICON_ROOT/${size}x${size}/apps"
    mkdir -p "$dest"
    cp "$ICONS/$APP_ID-$size.png" "$dest/$APP_ID.png"
done
mkdir -p "$ICON_ROOT/scalable/apps"
cp "$ICONS/$APP_ID.svg" "$ICON_ROOT/scalable/apps/$APP_ID.svg"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true
fi

echo "Installing launcher..."
mkdir -p "$APPS_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Seal Pomodoro
GenericName=Pomodoro Timer
Comment=A Pomodoro timer that lies on your desktop as a seal
Exec=python3 "$HERE/seal_pomodoro.py"
Path=$HERE
Icon=$APP_ID
Terminal=false
Categories=Utility;Clock;
Keywords=pomodoro;timer;focus;seal;
StartupWMClass=Seal-pomodoro
StartupNotify=false
EOF
chmod +x "$DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

# Desktop shortcut. Cinnamon/Nemo only run launchers marked executable and
# trusted, otherwise you get an "untrusted launcher" prompt.
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP_DIR" ]; then
    cp "$DESKTOP_FILE" "$DESKTOP_DIR/$APP_ID.desktop"
    chmod +x "$DESKTOP_DIR/$APP_ID.desktop"
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_DIR/$APP_ID.desktop" metadata::trusted true 2>/dev/null || true
    fi
    echo "Desktop shortcut: $DESKTOP_DIR/$APP_ID.desktop"
fi

echo
echo "Done. Launch it from the menu (search \"Seal\") or the desktop icon."
