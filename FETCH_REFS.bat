@echo off
REM Downloads every link in reference\<trip>\links.txt into that trip's folder, then analyses its style.
REM Make a new trip by creating reference\<trip>\links.txt
cd /d "%~dp0"
set PY="%~dp0.venv\Scripts\python.exe"
for /d %%T in (reference\*) do (
  if exist "%%T\links.txt" (
    echo.
    echo ===== %%~nxT =====
    %PY% -m yt_dlp -a "%%T\links.txt" -P "%%T" -o "%%(uploader)s_%%(id)s.%%(ext)s" -f "bv*[height<=1920]+ba/b" --merge-output-format mp4 --no-playlist --download-archive "%%T\_downloaded.txt" --cookies-from-browser firefox
    if errorlevel 1 %PY% -m yt_dlp -a "%%T\links.txt" -P "%%T" -o "%%(uploader)s_%%(id)s.%%(ext)s" -f "bv*[height<=1920]+ba/b" --merge-output-format mp4 --no-playlist --download-archive "%%T\_downloaded.txt"
    %PY% analyze_style.py --trip %%~nxT
  )
)
pause
