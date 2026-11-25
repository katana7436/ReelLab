@echo off
REM Double-click to install everything (FFmpeg, Python, Git, Claude Code, Python libs)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
