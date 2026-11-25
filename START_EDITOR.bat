@echo off
REM Opens the timeline editor for reels made by autocut.py. Close this window to stop it.
cd /d "%~dp0"
start "" http://127.0.0.1:8765
"%~dp0.venv\Scripts\python.exe" editor.py %*
pause
