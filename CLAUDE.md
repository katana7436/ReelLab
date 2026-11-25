# ReelLab — auto-edit workspace (D:\ReelLab)

Goal: fast-cut, cinematic 9:16 Instagram reels from travel footage, in the style of reference videos.
Machine: Windows laptop, Intel Iris Xe, no dedicated GPU. Keep renders at 1080x1920, preset veryfast.

## Layout (one subfolder per trip, e.g. himachal, kerala)
- `raw\<trip>\horizontal\`, `raw\<trip>\vertical\`  real clips, sorted by orientation (rotation tag respected)
- `raw\<trip>\live_photos\{horizontal,vertical}\`  iPhone Live Photo snippets (<=3.3s .MOV) - skipped by autocut
- `reference\<trip>\links.txt`  reference reel links; FETCH_REFS.bat downloads + analyses every trip
- `tools\probe_cache.json` orientation/duration of every clip; `tools\sort_manifest.csv` record of the sort
- Run: `autocut.py --trip himachal [--orientation vertical] --style`

- `raw\`        source clips (never modify or delete)
- `music\`      one song; the first file found is used
- `reference\`  reference reels to copy the style of; `links.txt` = URLs for yt-dlp
- `reference\_analysis\`  style.json, per-video json, contact sheets (`*_sheet.jpg`)
- `luts\`       .cube LUTs
- `output\`     everything generated

## Tools
- `analyze_style.py` – pacing (shot lengths, cuts/s, intro speed), beat sync, colour look + stats, speech (faster-whisper), contact sheet per reference.
- `autocut.py [--style] [--length N] [--lut x.cube] [--match-strength 0-1] [--no-preview]` – shot detection + scoring, beat-synced cuts, hero shot on the drop, FCPXML for Resolve + preview MP4. `--style` copies pacing and builds `output\match_reference.cube` (MKL colour transfer from my footage to the reference look).
- `make_captions.py video [--burn] [--lang hi] [--words 3]` – faster-whisper subtitles.
- `python -m yt_dlp` – download references (FETCH_REFS.bat).
- HyperFrames (`npx hyperframes ...`, skills installed) – HTML-based titles, location cards, lower-thirds, shader transitions rendered to MP4/MOV to overlay in Resolve.
- `auto-editor` – cut silences/dead air from talking clips. `ffmpeg-normalize` – loudness for Instagram (-14 LUFS).

## How to copy a reference style
1. Run analyze_style.py, then LOOK at each `*_sheet.jpg`: note framing (wide vs close), text overlays, transitions, speed ramps, letterboxing, grain.
2. Map what the numbers can't capture into changes: edit autocut.py (e.g. speed ramps, whip transitions), or build titles/overlays with HyperFrames.
3. Run `autocut.py --style --no-preview` while iterating; full renders are slow here.
4. Never put reference footage or audio into the output — copy style only.
