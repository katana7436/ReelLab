# ReelLab installer for Windows - everything goes into this folder (tools\ and .venv\), no admin needed,
# nothing added to your system PATH. Safe to run again: it skips what is already there.
#   Installs: Python 3.12 (portable), FFmpeg, the Python libraries in requirements.txt
#   Then runs selftest.py to prove it works.        Log: tools\install_log.txt
param([switch]$NoPause)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root  = $PSScriptRoot
$Tools = Join-Path $Root "tools"
$Dl    = Join-Path $Tools "_downloads"
$PyDir = Join-Path $Tools "python"
$FfDir = Join-Path $Tools "ffmpeg"
$Venv  = Join-Path $Root ".venv"
New-Item -ItemType Directory -Force $Tools, $Dl | Out-Null
Start-Transcript -Path (Join-Path $Tools "install_log.txt") -Force | Out-Null
function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Get-File($url, $out) { if (-not (Test-Path $out)) { Write-Host "  downloading $url"; Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing } }
$code = 1
try {
    Step "1/4 Python 3.12 (portable)"
    if (-not (Test-Path "$PyDir\python.exe")) {
        Get-File "https://www.nuget.org/api/v2/package/python/3.12.10" "$Dl\python-3.12.10.zip"
        $tmp = "$Tools\_pytmp"; if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        New-Item -ItemType Directory -Force $tmp | Out-Null
        tar -xf "$Dl\python-3.12.10.zip" -C $tmp
        if (Test-Path $PyDir) { Remove-Item $PyDir -Recurse -Force }
        Move-Item "$tmp\tools" $PyDir; Remove-Item $tmp -Recurse -Force
    } else { Write-Host "  already installed" }

    Step "2/4 FFmpeg"
    if (-not (Test-Path "$FfDir\bin\ffmpeg.exe")) {
        Get-File "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" "$Dl\ffmpeg.zip"
        $tmp = "$Tools\_fftmp"; if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        New-Item -ItemType Directory -Force $tmp | Out-Null
        tar -xf "$Dl\ffmpeg.zip" -C $tmp
        if (Test-Path $FfDir) { Remove-Item $FfDir -Recurse -Force }
        Move-Item (Get-ChildItem $tmp)[0].FullName $FfDir; Remove-Item $tmp -Recurse -Force
    } else { Write-Host "  already installed" }

    Step "3/4 Python libraries (a few minutes)"
    $cfg = "$Venv\pyvenv.cfg"
    if ((Test-Path $cfg) -and -not ((Get-Content $cfg -Raw) -match [regex]::Escape($PyDir))) {
        Write-Host "  folder was moved - rebuilding .venv"; Remove-Item $Venv -Recurse -Force
    }
    if (-not (Test-Path "$Venv\Scripts\python.exe")) { & "$PyDir\python.exe" -m venv $Venv }
    $Py = "$Venv\Scripts\python.exe"
    & $Py -m pip install --upgrade pip --quiet
    & $Py -m pip install -r "$Root\requirements.txt" --quiet
    if ($LASTEXITCODE) { throw "pip install failed" }

    Step "4/4 Self-test"
    & $Py "$Root\selftest.py"
    $code = $LASTEXITCODE
} catch {
    Write-Host "INSTALL ERROR: $_" -ForegroundColor Red
}
Stop-Transcript | Out-Null
if ($code -eq 0) { Write-Host "`nDone! Next: put clips in raw\<trip>\, a song in music\, then double-click MAKE_REEL.bat" -ForegroundColor Green }
else { Write-Host "`nSomething failed - see tools\install_log.txt (you can run INSTALL.bat again)" -ForegroundColor Red }
if (-not $NoPause) { Read-Host "Press Enter to close" }
exit $code
