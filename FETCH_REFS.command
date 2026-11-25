#!/bin/bash
# Double-click: downloads every link in reference/<trip>/links.txt, then analyses its style.
cd "$(dirname "$0")"
PY=./.venv/bin/python
for T in reference/*/; do
  T="${T%/}"; [ -f "$T/links.txt" ] || continue
  echo; echo "===== $(basename "$T") ====="
  "$PY" -m yt_dlp -a "$T/links.txt" -P "$T" -o "%(uploader)s_%(id)s.%(ext)s" -f "bv*[height<=1920]+ba/b" \
      --merge-output-format mp4 --no-playlist --download-archive "$T/_downloaded.txt"
  "$PY" analyze_style.py --trip "$(basename "$T")"
done
echo; read -n 1 -s -r -p "Press any key to close"
