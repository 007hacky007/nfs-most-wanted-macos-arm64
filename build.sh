#!/bin/sh
set -eu
exec python3 "${0%/*}/tools/build_app.py" "$@"
