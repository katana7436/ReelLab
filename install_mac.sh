#!/bin/bash
# ReelLab installer for macOS (Apple Silicon or Intel) and Linux.
# Everything goes into this folder (tools/ and .venv/): no admin password, no Homebrew needed,
# nothing added to your shell profile. Safe to run again: it skips what is already there.
#   Installs: uv (Python installer) -> Python 3.12, FFmpeg + FFprobe, the libraries in requirements.txt
#   Then runs selftest.py to prove it works.        Log: tools/install_log.txt
# Usage:  bash install_mac.sh        (or double-click INSTALL.command)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$ROOT/tools"; BIN="$TOOLS/bin"; DL="$TOOLS/_downloads"
mkdir -p "$BIN" "$DL"
exec > >(tee "$TOOLS/install_log.txt") 2>&1
step() { printf '\n\033[36m=== %s\033[0m\n' "$1"; }
fetch() { echo "  downloading $1"; curl -fL --retry 3 --progress-bar -o "$2" "$1"; }

OS="$(uname -s)"; ARCH="$(uname -m)"
case "$ARCH" in arm64|aarch64) A=aarch64; FA=arm64 ;; x86_64) A=x86_64; FA=amd64 ;; *) echo "unsupported CPU $ARCH"; exit 1 ;; esac
case "$OS" in Darwin) UVT="$A-apple-darwin"; FOS=macos ;; Linux) UVT="$A-unknown-linux-gnu"; FOS=linux ;; *) echo "unsupported OS $OS"; exit 1 ;; esac
echo "ReelLab install on $OS $ARCH in $ROOT"

# macOS marks files from a browser download as 'quarantined', which blocks double-clicking
# the .command launchers. Clear that flag for this folder only.
[ "$OS" = Darwin ] && xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true
chmod +x "$ROOT"/*.command "$ROOT"/*.sh 2>/dev/null || true

step "1/4 uv (installs Python for this folder only)"
if [ ! -x "$BIN/uv" ]; then
  fetch "https://github.com/astral-sh/uv/releases/latest/download/uv-$UVT.tar.gz" "$DL/uv.tar.gz"
  tar -xzf "$DL/uv.tar.gz" -C "$DL" && mv "$DL/uv-$UVT/uv" "$BIN/uv" && chmod +x "$BIN/uv"
else echo "  already installed"; fi
export UV_PYTHON_INSTALL_DIR="$TOOLS/python" UV_CACHE_DIR="$TOOLS/cache/uv" UV_PYTHON_PREFERENCE=only-managed

step "2/4 FFmpeg + FFprobe"
if [ ! -x "$BIN/ffmpeg" ] || [ ! -x "$BIN/ffprobe" ]; then
  for t in ffmpeg ffprobe; do
    if [ "$OS" = Darwin ]; then
      # static builds by Martin Riedl (native for Apple Silicon and Intel)
      fetch "https://ffmpeg.martin-riedl.de/redirect/latest/$FOS/$FA/release/$t.zip" "$DL/$t.zip"
      unzip -o -q "$DL/$t.zip" -d "$BIN" && chmod +x "$BIN/$t"
    else
      if command -v $t >/dev/null; then ln -sf "$(command -v $t)" "$BIN/$t";
      else echo "  please install ffmpeg with your package manager (e.g. sudo apt install ffmpeg) and run again"; exit 1; fi
    fi
  done
  [ "$OS" = Darwin ] && xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true
else echo "  already installed"; fi
"$BIN/ffmpeg" -version | sed -n 1p   # (not head: it would break the pipe under pipefail)

step "3/4 Python 3.12 + libraries (a few minutes)"
if [ -f "$ROOT/.venv/pyvenv.cfg" ] && ! grep -q "$TOOLS/python" "$ROOT/.venv/pyvenv.cfg"; then
  echo "  folder was moved - rebuilding .venv"; rm -rf "$ROOT/.venv"
fi
[ -x "$ROOT/.venv/bin/python" ] || "$BIN/uv" venv --python 3.12 "$ROOT/.venv"
"$BIN/uv" pip install --python "$ROOT/.venv/bin/python" -r "$ROOT/requirements.txt"

step "4/4 Self-test"
if "$ROOT/.venv/bin/python" "$ROOT/selftest.py"; then
  printf '\n\033[32mDone! Next: put clips in raw/<trip>/, a song in music/, then double-click MAKE_REEL.command\033[0m\n'
else
  printf '\n\033[31mSomething failed - see tools/install_log.txt (you can run the installer again)\033[0m\n'; exit 1
fi
