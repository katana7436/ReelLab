@echo off
REM Builds a reel from raw\<trip>\ (skips live_photos) in the style of reference\<trip>\
cd /d "%~dp0"
set /p TRIP=Trip folder (e.g. himachal): 
set /p ORI=Orientation - h, v or Enter for both: 
set OPT=
if /i "%ORI%"=="h" set OPT=--orientation horizontal
if /i "%ORI%"=="v" set OPT=--orientation vertical
if exist "reference\%TRIP%\_analysis\style.json" (
  "%~dp0.venv\Scripts\python.exe" autocut.py --trip %TRIP% %OPT% --style
) else (
  "%~dp0.venv\Scripts\python.exe" autocut.py --trip %TRIP% %OPT% --length 30
)
pause
