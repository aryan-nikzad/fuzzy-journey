#!/usr/bin/env bash
# Take headless screenshots of every page into docs/screenshots/.
# Needs: xvfb, imagemagick, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, adwaita-icon-theme.
set -euo pipefail
cd "$(dirname "$0")/.."
out=docs/screenshots
mkdir -p "$out"
export XDG_DATA_HOME="$(mktemp -d)"
export GSK_RENDERER=cairo GDK_BACKEND=x11 NO_AT_BRIDGE=1 PYTHONPATH=.
export FUZZY_JOURNEY_NOW="${FUZZY_JOURNEY_NOW:-2026-11-02T10:15}" FUZZY_JOURNEY_DEMO=1
python3 scripts/seed_demo.py >/dev/null
Xvfb :98 -screen 0 760x860x24 >/dev/null 2>&1 &
xvfb=$!
export DISPLAY=:98
trap 'kill $xvfb 2>/dev/null || true' EXIT
sleep 1
for scheme in light dark; do
  for page in today routine bank alarms prayers; do
    FUZZY_JOURNEY_PAGE=$page python3 -c "
import sys; from fuzzy_journey.database import Database
Database().settings.theme='$scheme'" 
    FUZZY_JOURNEY_PAGE=$page python3 -m fuzzy_journey >/dev/null 2>&1 &
    pid=$!
    sleep 4
    import -window root "$out/$page-$scheme.png"
    kill $pid 2>/dev/null || true
    wait $pid 2>/dev/null || true
  done
done
echo "Screenshots in $out"
