#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/fuzzy-journey/app"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
SERVICE_DIR="$HOME/.config/systemd/user"

if ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw' >/dev/null 2>&1; then
    echo "Missing GTK 4 / libadwaita Python bindings."
    echo "On Ubuntu, install them with:"
    echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libnotify-bin"
    exit 1
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$SERVICE_DIR"
cp -a "$SOURCE_DIR/fuzzy_journey" "$APP_DIR/"
cp -a "$SOURCE_DIR/assets" "$APP_DIR/"
cp "$SOURCE_DIR/prayer_aio.py" "$APP_DIR/"
cp "$SOURCE_DIR/shahrekord_prayer_times_2026_schedule.csv" "$APP_DIR/"
if [ -f "$SOURCE_DIR/shahrekord_prayer_times_2026_raw.csv" ]; then
    cp "$SOURCE_DIR/shahrekord_prayer_times_2026_raw.csv" "$APP_DIR/"
fi
cp "$SOURCE_DIR/README.md" "$APP_DIR/"

cat > "$BIN_DIR/fuzzy-journey" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR"
exec /usr/bin/python3 -m fuzzy_journey.gui "$@"
EOF
chmod +x "$BIN_DIR/fuzzy-journey"

cat > "$DESKTOP_DIR/fuzzy-journey.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Fuzzy Journey
Comment=Your day, shaped around prayer and focused work
Exec=$BIN_DIR/fuzzy-journey
Icon=$APP_DIR/assets/fuzzy-journey.svg
Terminal=false
Categories=Office;Utility;Calendar;
StartupNotify=true
StartupWMClass=fuzzy-journey
EOF

cat > "$SERVICE_DIR/fuzzy-journey.service" <<EOF
[Unit]
Description=Fuzzy Journey offline alarm scheduler
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONPATH=$APP_DIR
ExecStart=/usr/bin/python3 -m fuzzy_journey.alarm_daemon
Restart=on-failure
RestartSec=4

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now fuzzy-journey.service

echo
echo "Fuzzy Journey is installed."
echo "  App:     $BIN_DIR/fuzzy-journey"
echo "  Service: systemctl --user status fuzzy-journey"
echo "  Data:    $HOME/.local/share/fuzzy-journey"
echo
echo "Launch Fuzzy Journey from the applications menu."
