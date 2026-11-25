"""Shared paths for every ReelLab script (Windows, macOS, Linux).

- ROOT: the ReelLab folder (where the scripts are).
- DATA: where raw\\, music\\, reference\\ and output\\ live. Same as ROOT unless the
  REELLAB_HOME environment variable points somewhere else (the self-test uses this).
- Puts the ffmpeg that INSTALL downloaded (tools/ffmpeg/bin or tools/bin) first on PATH,
  so nothing has to be added to the system PATH.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("REELLAB_HOME") or ROOT).resolve()

_exe = ".exe" if os.name == "nt" else ""
for _d in (ROOT / "tools" / "ffmpeg" / "bin", ROOT / "tools" / "bin"):
    if (_d / f"ffmpeg{_exe}").exists():
        os.environ["PATH"] = str(_d) + os.pathsep + os.environ.get("PATH", "")
        break

INSTALL_HINT = "run INSTALL first (INSTALL.bat on Windows, INSTALL.command on Mac)"
