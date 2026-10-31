#!/bin/sh
# Renders background.html to background.png (1x) and background@2x.png (2x).
# Each render gets its own throwaway Chrome profile; reusing one can hang the second run.
set -eu
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
for scale in 1 2; do
  if [ "$scale" = 1 ]; then out=background.png; else out="background@2x.png"; fi
  profile=$(mktemp -d)
  "$CHROME" --headless --disable-gpu --hide-scrollbars --user-data-dir="$profile" \
    --force-device-scale-factor="$scale" --window-size=760,600 \
    --virtual-time-budget=5000 --screenshot="$PWD/$out" "file://$PWD/background.html"
  rm -rf "$profile"
done
