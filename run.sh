#!/usr/bin/env bash
# Run straight from the source tree, without installing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT"
exec /usr/bin/python3 -m fuzzy_journey "$@"
