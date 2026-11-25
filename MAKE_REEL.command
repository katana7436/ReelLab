#!/bin/bash
# Double-click: builds a reel from raw/<trip>/ (skips live_photos), cut to the song in music/
cd "$(dirname "$0")"
PY=./.venv/bin/python
[ -x "$PY" ] || { echo "ReelLab is not installed yet - double-click INSTALL.command first."; read -n 1 -s; exit 1; }
echo "Trip folders in raw/: $(ls raw 2>/dev/null | tr '\n' ' ')"
read -r -p "Trip folder (e.g. goa): " TRIP
read -r -p "Orientation - h, v or Enter for both: " ORI
OPT=()
[ "$ORI" = h ] && OPT=(--orientation horizontal)
[ "$ORI" = v ] && OPT=(--orientation vertical)
if [ -f "reference/$TRIP/_analysis/style.json" ]; then
  "$PY" autocut.py --trip "$TRIP" "${OPT[@]}" --style
else
  "$PY" autocut.py --trip "$TRIP" "${OPT[@]}" --length 30
fi
echo; read -n 1 -s -r -p "Done - your reel is in output/$TRIP/. Press any key to close"
