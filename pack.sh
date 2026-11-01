#!/bin/sh
# Package out/nfsmw_boot with a prepared game folder: ./pack.sh --game out/installed
# The app always carries the game, so packaging without --game is refused.
set -eu
cd "$(dirname "$0")"
exec .venv/bin/python tools/package_app.py "$@"
