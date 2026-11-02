#!/usr/bin/env bash
# Remove the application. Your alarms, settings and timetables are kept.
set -euo pipefail
APP_ID="org.anyatech.FuzzyJourney"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"

systemctl --user disable --now fuzzy-journey.service 2>/dev/null || true
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/fuzzy-journey.service"
systemctl --user daemon-reload 2>/dev/null || true

rm -f "$DATA_DIR/applications/$APP_ID.desktop" "$DATA_DIR/applications/fuzzy-journey.desktop"
rm -f "$DATA_DIR/icons/hicolor/scalable/apps/$APP_ID.svg"
rm -f "$HOME/.local/bin/fuzzy-journey" "$HOME/.local/bin/fuzzy-journey-planner"
rm -rf "$DATA_DIR/fuzzy-journey/app"

echo "Fuzzy Journey was removed."
echo "Your data is still in $DATA_DIR/fuzzy-journey (delete that folder to remove it too)."
