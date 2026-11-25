#!/bin/bash
# Double-click: opens the timeline editor in your browser. Close this window to stop it.
cd "$(dirname "$0")"
PY=./.venv/bin/python
[ -x "$PY" ] || { echo "ReelLab is not installed yet - double-click INSTALL.command first."; read -n 1 -s; exit 1; }
"$PY" editor.py --open "$@"
