@echo off
REM Opens the timeline editor in your browser. Close this window to stop it.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo ReelLab is not installed yet - double-click INSTALL.bat first. & pause & exit /b 1)
"%~dp0.venv\Scripts\python.exe" editor.py --open %*
pause
