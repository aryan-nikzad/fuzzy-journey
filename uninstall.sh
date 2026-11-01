#!/usr/bin/env bash
set -euo pipefail
systemctl --user disable --now fuzzy-journey.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/fuzzy-journey.service"
rm -f "$HOME/.local/share/applications/fuzzy-journey.desktop"
rm -f "$HOME/.local/share/applications/org.anyatech.FuzzyJourney.desktop"
rm -f "$HOME/.local/bin/fuzzy-journey"
systemctl --user daemon-reload
rm -rf "$HOME/.local/share/fuzzy-journey/app"
echo "Fuzzy Journey application removed. Your local alarms and data were kept."
