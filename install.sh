#!/usr/bin/env bash
# Install Fuzzy Journey for the current user (no root needed). Safe to re-run to update.
set -euo pipefail

APP_ID="org.anyatech.FuzzyJourney"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_DIR/fuzzy-journey/app"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$DATA_DIR/applications"
ICON_DIR="$DATA_DIR/icons/hicolor/scalable/apps"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PYTHON=/usr/bin/python3

if ! "$PYTHON" -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw; assert Adw.MINOR_VERSION >= 4 or Adw.MAJOR_VERSION > 1' >/dev/null 2>&1; then
    echo "Fuzzy Journey needs GTK 4 and libadwaita 1.4 or newer (Ubuntu 24.04+, Fedora 39+)."
    echo "On Ubuntu, install the bindings with:"
    echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libnotify-bin"
    exit 1
fi

mkdir -p "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$SERVICE_DIR"

# Replace the application folder wholesale so no stale files from older versions linger.
# (Your alarms, settings and downloaded timetables live next to it and are never touched.)
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -a "$SOURCE_DIR/fuzzy_journey" "$APP_DIR/"
cp "$SOURCE_DIR/prayer_aio.py" "$APP_DIR/"
find "$APP_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

install -m 0644 "$SOURCE_DIR/fuzzy_journey/resources/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg"

cat > "$BIN_DIR/fuzzy-journey" <<LAUNCHER
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR"
exec $PYTHON -m fuzzy_journey "\$@"
LAUNCHER

cat > "$BIN_DIR/fuzzy-journey-planner" <<LAUNCHER
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR"
exec $PYTHON "$APP_DIR/prayer_aio.py" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/fuzzy-journey" "$BIN_DIR/fuzzy-journey-planner"

rm -f "$DESKTOP_DIR/fuzzy-journey.desktop"
cat > "$DESKTOP_DIR/$APP_ID.desktop" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Fuzzy Journey
Comment=Your day, shaped around prayer and focused work
Exec=$BIN_DIR/fuzzy-journey
TryExec=$BIN_DIR/fuzzy-journey
Icon=$APP_ID
Terminal=false
Categories=Office;Utility;Calendar;
StartupNotify=true
StartupWMClass=$APP_ID
DESKTOP

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA_DIR/icons/hicolor" >/dev/null 2>&1 || true

cat > "$SERVICE_DIR/fuzzy-journey.service" <<SERVICE
[Unit]
Description=Fuzzy Journey offline alarm service
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONPATH=$APP_DIR
ExecStart=$PYTHON -m fuzzy_journey.service
Restart=on-failure
RestartSec=4

[Install]
WantedBy=default.target
SERVICE

systemctl --user daemon-reload
systemctl --user enable fuzzy-journey.service >/dev/null 2>&1
systemctl --user restart fuzzy-journey.service

if ! command -v notify-send >/dev/null 2>&1; then
    echo "Optional: install libnotify-bin to see desktop notifications when an alarm rings:"
    echo "  sudo apt install libnotify-bin"
fi
if ! command -v mpv >/dev/null 2>&1 && ! command -v ffplay >/dev/null 2>&1 \
   && ! command -v mpg123 >/dev/null 2>&1 && ! command -v cvlc >/dev/null 2>&1; then
    echo "Optional: install mpv to use your own MP3/OGG alarm sounds:"
    echo "  sudo apt install mpv"
fi

echo
echo "Fuzzy Journey is installed."
echo "  Open it from the applications menu, or run: fuzzy-journey"
echo "  Alarm service: systemctl --user status fuzzy-journey"
echo "  Your data:     $DATA_DIR/fuzzy-journey"
