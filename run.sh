#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT"
exec /usr/bin/python3 -m fuzzy_journey.gui "$@"
