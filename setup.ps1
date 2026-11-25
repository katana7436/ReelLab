# ReelLab AI video pipeline - portable install, everything on this drive, no admin needed.
# Installs into .\tools : Node.js LTS (22+), FFmpeg, Git (portable, incl. bash + LFS), Python 3.12
# Then: Python venv (.venv) with openai-whisper (CPU torch) + yt-dlp + pipeline libs,
#       HyperFrames (local npm) + its agent skills, Claude Code (npm, on D:).
# Results: tools\versions.txt   Full log: tools\install_log.txt

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root   = $PSScriptRoot
$Tools  = Join-Path $Root "tools"
$Dl     = Join-Path $Tools "_downloads"
$Cache  = Join-Path $Tools "cache"
$TestD  = Join-Path $Tools "_test"
$Log    = Join-Path $Tools "install_log.txt"
$Ver    = Join-Path $Tools "versions.txt"
$NodeDir = Join-Path $Tools "node"
$FfDir   = Join-Path $Tools "ffmpeg"
$GitDir  = Join-Path $Tools "git"
$PyDir   = Join-Path $Tools "python"
$NpmG    = Join-Path $Tools "npm-global"
$Venv    = Join-Path $Root ".venv"
New-Item -ItemType Directory -Force $Tools, $Dl, $Cache, $TestD, $NpmG | Out-Null
Start-Transcript -Path $Log -Force | Out-Null
"STARTED $(Get-Date)" | Set-Content $Ver

function Step($msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }
function Get-File($url, $out) {
    if (-not (Test-Path $out)) { Write-Host "  downloading $url"; Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing }
}
function Expand-Flat($zip, $dest) {
    $tmp = "$dest._tmp"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force $tmp | Out-Null
    tar -xf $zip -C $tmp
    $items = @(Get-ChildItem $tmp)
    $src = if ($items.Count -eq 1 -and $items[0].PSIsContainer) { $items[0].FullName } else { $tmp }
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Move-Item $src $dest
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
}
function Add-UserPath([string[]]$dirs) {
    $cur = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($cur -split ";" | Where-Object { $_ -and ($dirs -notcontains $_) })
    [Environment]::SetEnvironmentVariable("Path", (($dirs + $parts) -join ";"), "User")
    $env:Path = ($dirs -join ";") + ";" + $env:Path
}
function Set-UserEnv($k, $v) { [Environment]::SetEnvironmentVariable($k, $v, "User"); Set-Item "env:$k" $v }

# Keep every cache (models, pip, npm, headless Chrome) on this drive
Set-UserEnv XDG_CACHE_HOME      $Cache                       # Whisper models
Set-UserEnv PIP_CACHE_DIR       (Join-Path $Cache "pip")
Set-UserEnv npm_config_cache    (Join-Path $Cache "npm")
Set-UserEnv npm_config_prefix   $NpmG
Set-UserEnv PUPPETEER_CACHE_DIR (Join-Path $Cache "puppeteer") # HyperFrames' Chrome
Set-UserEnv HF_HOME             (Join-Path $Cache "huggingface")

# ---------------- prerequisites ----------------
try {
Step "1/8 Node.js LTS (22+)"
$haveNode = (Test-Path "$NodeDir\node.exe") -and ([int]((& "$NodeDir\node.exe" -v).TrimStart('v').Split('.')[0]) -ge 22)
if (-not $haveNode) {
    $all = Invoke-RestMethod "https://nodejs.org/dist/index.json"
    $rel = @($all) | ForEach-Object { $_ } |
           Where-Object { $_.lts -and [int]($_.version.TrimStart('v').Split('.')[0]) -ge 22 } | Select-Object -First 1
    $nv = $rel.version
    if ($nv -notmatch '^v\d+\.\d+\.\d+$') { throw "Could not work out the Node.js version (got '$nv')" }
    Get-File "https://nodejs.org/dist/$nv/node-$nv-win-x64.zip" "$Dl\node-$nv.zip"
    Expand-Flat "$Dl\node-$nv.zip" $NodeDir
} else { Write-Host "  already installed" }

Step "2/8 FFmpeg"
if (-not (Test-Path "$FfDir\bin\ffmpeg.exe")) {
    Get-File "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" "$Dl\ffmpeg.zip"
    Expand-Flat "$Dl\ffmpeg.zip" $FfDir
} else { Write-Host "  already installed" }

Step "3/8 Git (portable, with bash + LFS)"
if (-not (Test-Path "$GitDir\cmd\git.exe")) {
    $gr = Invoke-RestMethod "https://api.github.com/repos/git-for-windows/git/releases/latest" -Headers @{ "User-Agent" = "setup" }
    $asset = $gr.assets | Where-Object { $_.name -match '^PortableGit-.*-64-bit\.7z\.exe$' } | Select-Object -First 1
    Get-File $asset.browser_download_url "$Dl\$($asset.name)"
    Start-Process -FilePath "$Dl\$($asset.name)" -ArgumentList "-o`"$GitDir`"", "-y" -Wait
} else { Write-Host "  already installed" }
Set-UserEnv CLAUDE_CODE_GIT_BASH_PATH "$GitDir\bin\bash.exe"

Step "4/8 Python 3.12 (portable package into tools\python)"
if (-not (Test-Path "$PyDir\python.exe")) {
    # NuGet's 'python' package is a complete, self-contained Python (pip + venv), no registry, no admin
    Get-File "https://www.nuget.org/api/v2/package/python/3.12.10" "$Dl\python-3.12.10.zip"
    $tmp = "$Tools\_pytmp"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force $tmp | Out-Null
    tar -xf "$Dl\python-3.12.10.zip" -C $tmp
    if (Test-Path $PyDir) { Remove-Item $PyDir -Recurse -Force }
    Move-Item "$tmp\tools" $PyDir
    Remove-Item $tmp -Recurse -Force
    if (-not (Test-Path "$PyDir\python.exe")) { throw "Portable Python did not unpack to $PyDir" }
} else { Write-Host "  already installed" }

Add-UserPath @($NodeDir, $NpmG, "$FfDir\bin", "$GitDir\cmd", "$Venv\Scripts")
$env:GIT_LFS_SKIP_SMUDGE = "1"   # HyperFrames skills: source only, skip large LFS media

# ---------------- Python tools ----------------
Step "5/8 Python venv + Whisper (CPU) + yt-dlp + pipeline libs"
if (-not (Test-Path "$Venv\Scripts\python.exe")) { & "$PyDir\python.exe" -m venv $Venv }
# Folder was moved/renamed? Point the venv at this folder's Python and rebuild command launchers
$cfg = "$Venv\pyvenv.cfg"
if ((Test-Path $cfg) -and -not ((Get-Content $cfg -Raw) -match [regex]::Escape($PyDir))) {
    Write-Host "  folder moved - repairing Python environment paths"
    & "$PyDir\python.exe" -m venv --upgrade $Venv
    & "$Venv\Scripts\python.exe" -m pip install --force-reinstall --no-deps --no-cache-dir pip yt-dlp openai-whisper auto-editor ffmpeg-normalize scenedetect
}
$Py = "$Venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install torch --index-url https://download.pytorch.org/whl/cpu
& $Py -m pip install openai-whisper yt-dlp
& $Py -m pip install -r "$Root\requirements.txt"

# ---------------- HyperFrames ----------------
Step "6/8 HyperFrames (local to this folder)"
Push-Location $Root
if (-not (Test-Path "$Root\package.json")) { & "$NodeDir\npm.cmd" init -y | Out-Null }
& "$NodeDir\npm.cmd" install hyperframes@latest

Step "7/8 HyperFrames agent skills"
& "$NodeDir\npx.cmd" --yes skills add heygen-com/hyperframes --full-depth --yes
Pop-Location

Step "8/8 Claude Code (installed under tools\npm-global)"
& "$NodeDir\npm.cmd" install -g @anthropic-ai/claude-code
} catch {
    Write-Host "INSTALL ERROR: $_" -ForegroundColor Red
    "INSTALL ERROR: $_" | Add-Content $Ver
}

# ---------------- checks ----------------
Write-Host "`n=== Checking every tool" -ForegroundColor Green
$ErrorActionPreference = "Continue"
"--- RESULTS ---" | Add-Content $Ver
function Run([string]$exe, [string[]]$a) {
    try { $o = & $exe @a 2>&1 | Out-String; return @{ ok = ($LASTEXITCODE -eq 0); out = $o.Trim() } }
    catch { return @{ ok = $false; out = "$_" } }
}
function Report($name, $version, $ok, $detail) {
    $line = "{0,-12} | {1,-40} | {2}" -f $name, $version, ($(if ($ok) { "WORKS" } else { "FAILED" }) + " - " + $detail)
    Write-Host $line -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
    $line | Add-Content $Ver
}
$Py = "$Venv\Scripts\python.exe"

$r = Run "$NodeDir\node.exe" @("-v"); $n = Run "$NodeDir\npm.cmd" @("-v")
$major = if ($r.out -match '^v(\d+)') { [int]$Matches[1] } else { 0 }
Report "Node.js" "$($r.out) (npm $($n.out))" ($r.ok -and $major -ge 22) "needs 22+"

$r = Run "$FfDir\bin\ffmpeg.exe" @("-version")
$fv = ($r.out -split "`n")[0] -replace "ffmpeg version ", "" -replace " Copyright.*", ""
$t = Run "$FfDir\bin\ffmpeg.exe" @("-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=2",
     "-f", "lavfi", "-i", "sine=f=440:d=2", "-c:v", "libx264", "-preset", "veryfast", "-shortest", "$TestD\ffmpeg_test.mp4")
Report "FFmpeg" $fv ($t.ok -and (Test-Path "$TestD\ffmpeg_test.mp4")) "rendered a 2s 1080x1920 test clip"

$r = Run "$GitDir\cmd\git.exe" @("--version")
Report "Git" ($r.out -replace "git version ", "") $r.ok "portable"

$r = Run $Py @("--version")
Report "Python" ($r.out -replace "Python ", "") $r.ok "venv at .venv"

# Whisper: synthesise a spoken sentence with Windows' built-in voice, then transcribe it
try {
    Add-Type -AssemblyName System.Speech
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.SetOutputToWaveFile("$TestD\speech.wav"); $s.Speak("Hello from Himachal Pradesh. This is a caption test."); $s.Dispose()
} catch {}
$v = Run $Py @("-c", "import whisper; print(whisper.__version__)")
$t = Run "$Venv\Scripts\whisper.exe" @("$TestD\speech.wav", "--model", "tiny", "--language", "en", "--fp16", "False",
     "--output_dir", $TestD, "--output_format", "txt")
$txt = if (Test-Path "$TestD\speech.txt") { (Get-Content "$TestD\speech.txt" -Raw).Trim() } else { "" }
Report "Whisper" $v.out ($t.ok -and $txt.Length -gt 0) "heard: '$txt'"

$r = Run "$Venv\Scripts\yt-dlp.exe" @("--version")
$t = Run "$Venv\Scripts\yt-dlp.exe" @("--simulate", "--no-warnings", "--print", "title", "https://www.youtube.com/watch?v=jNQXAC9IVRw")
Report "yt-dlp" $r.out ($r.ok -and $t.ok) "read video title: '$($t.out)'"

Push-Location $Root
$r = Run "$NodeDir\npx.cmd" @("--no-install", "hyperframes", "--version")
$d = Run "$NodeDir\npx.cmd" @("--no-install", "hyperframes", "doctor")
Pop-Location
$d.out | Set-Content "$Tools\hyperframes_doctor.txt"
$skills = @(Get-ChildItem -Path $Root -Recurse -Depth 4 -Filter SKILL.md -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "hyperframes|media-use" -and $_.FullName -notmatch "node_modules" }).Count
Report "HyperFrames" ($r.out -split "`n")[-1] ($r.ok -and $d.ok) "doctor: $(if ($d.ok) {'passed'} else {'see tools\hyperframes_doctor.txt'}); $skills agent skills installed"

$r = Run "$NpmG\claude.cmd" @("--version")
Report "Claude Code" $r.out $r.ok "on D:"

"FINISHED $(Get-Date)" | Add-Content $Ver
Stop-Transcript | Out-Null
Write-Host "`nResults saved to tools\versions.txt. Open a NEW terminal so PATH changes apply."
Read-Host "Press Enter to close"
