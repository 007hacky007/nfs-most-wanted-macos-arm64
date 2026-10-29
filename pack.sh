#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec .venv/bin/python tools/package_app.py "$@"
