# ReelLab

Turns your travel footage into fast-cut, beat-synced 9:16 Instagram reels that copy the pacing and colour of reels you like.
It also includes a timeline editor in your browser and one-click posting to Instagram.
Everything runs on your own PC: no subscription, no paid AI, and your footage never leaves your computer.

## Install (Windows 10/11)
You need about **6 GB free disk** and internet for the first install. No admin rights are needed.
1. On this GitHub page click **Code > Download ZIP**, then extract it, e.g. to `D:\ReelLab`. A short path without spaces is safest.
2. Double-click **`INSTALL.bat`**. It downloads Python, FFmpeg, Node.js, Git and the AI models into the folder's `tools\` (10-30 min).
   It ends with a table and every line should say WORKS. If Windows SmartScreen warns, click *More info > Run anyway*.
3. Open a **new** terminal or restart so the PATH changes apply.

Uninstall by deleting the folder. The installer also adds a few user environment variables (PATH and cache folders) pointing into it.

## Quick start
1. Copy your clips into `raw\<trip>\` (e.g. `raw\goa\`). Splitting them into `horizontal\` / `vertical\` subfolders is optional.
2. Put one song in `music\`.
3. Optional: put links to reels whose style you want to copy in `reference\<trip>\links.txt`, one per line, then run `FETCH_REFS.bat`.
4. Double-click `MAKE_REEL.bat` and type the trip name.
5. Double-click `START_EDITOR.bat` to watch, fix and render the reel, then post it.

Use your own footage and music you're allowed to use. Reference reels are only analysed for style: never repost other people's videos or audio.

## Folders
| Folder | What |
|---|---|
| `raw\<trip>\horizontal\`, `raw\<trip>\vertical\` | your clips (never modified) |
| `music\` | one song, the first audio file found is used |
| `reference\<trip>\links.txt` | links to reels whose style you want to copy |
| `output\<trip>\` | everything generated |

Trip names must match between `raw\` and `reference\` (e.g. `himachal`, `kerala`).

## Make a reel
1. Put a song in `music\`.
2. `FETCH_REFS.bat`: downloads the reference reels and writes `reference\<trip>\_analysis\style.json`.
3. `MAKE_REEL.bat` (asks for the trip), or:
   ```powershell
   .\.venv\Scripts\python.exe autocut.py --trip kerala --style --no-preview
   ```
   Writes `output\<trip>\reel_timeline.fcpxml` (DaVinci Resolve: File > Import > Timeline),
   `timeline.json` (for the editor), `shots.json`, and, without `--no-preview`, `reel_preview.mp4`.

## Edit the timeline
```powershell
.\.venv\Scripts\python.exe editor.py
```
Then open http://127.0.0.1:8765. Each block on the bottom track is one cut, and the ticks on the ruler are music beats.
- Click a clip, then pick a different shot on the right, or drag on the filmstrip to choose which part of the shot plays.
- Move earlier/later, split on a beat, merge, delete, or toggle hero. Undo with Ctrl+Z.
- **Save** rewrites `timeline.json` (the old one becomes `timeline.prev.json`) and `reel_timeline.fcpxml`.
- **Render preview** makes the full-quality `reel_preview.mp4`. This is slow on this laptop.

The editor plays low-res preview clips stored in `output\<trip>\_editor_cache\`. Your 4K HEVC footage won't play in a browser directly. The cache is safe to delete.
Clip lengths stay on the beat grid, so swapping or moving changes which shot fills a slot, not how long the slot is.

**Editing a video that's already rendered** (e.g. `output\himachal\Himachal_ref2_v2.mp4`): an MP4 has no timeline inside it, so import it first.
```powershell
.\.venv\Scripts\python.exe import_video.py output\himachal\Himachal_ref2_v2.mp4
```
This detects the cuts (one clip per cut, use `--threshold 20` for more cuts) into `output\himachal_ref2_v2\`, using the video's own soundtrack.
You can reorder, trim, change length, split, delete and render. Titles burned into the picture stay, and the clips can't be swapped for raw shots. The original MP4 is never changed.

Shortcut: double-click `START_EDITOR.bat`. Opening `editor\index.html` directly does not work, because it needs the server.

## Other tools
- `make_captions.py video [--burn] [--lang hi]`: subtitles (faster-whisper)
- `npx hyperframes ...`: titles and overlays rendered as video
- `setup.ps1` / `INSTALL.bat`: (re)install everything into this folder. Re-run it if the folder is moved again.

## Post to Instagram
`insta_post.py` publishes a rendered reel using Instagram's official API. The file is uploaded straight from this laptop, so no public link is needed.
```powershell
.\.venv\Scripts\python.exe insta_post.py --check
.\.venv\Scripts\python.exe insta_post.py output\kerala\reel_preview.mp4 --caption "Kerala" --dry-run
.\.venv\Scripts\python.exe insta_post.py output\kerala\reel_preview.mp4 --caption-file caption.txt
```
It always asks "Type yes" before posting (skip that with `--yes`). In the editor, **Post to Instagram** does the same for the last render.

One-time setup, about 20 minutes (Meta renames its menus often, so look for these words):
1. **Instagram app**: Settings > Account type and tools > *Switch to professional account* (Creator is fine, and it's free).
2. **Link it to a Facebook Page.** Create a Page if you don't have one, then in the Page's settings go to *Linked accounts > Instagram*.
3. Go to **developers.facebook.com** > My Apps > *Create app*. Choose the Business type / the use case that manages Instagram content, then add the Instagram product with *Facebook Login for Business*. In Development mode it can post to your own account without Meta's app review.
4. In the **Graph API Explorer**, pick your app and add the permissions `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement` and `business_management`. Then click *Generate Access Token*.
5. **Get your Instagram account ID.** In the Explorer, run `me/accounts?fields=instagram_business_account`. The number inside `instagram_business_account` is `IG_USER_ID`.
6. **Make the token last ~60 days.** Open the *Access Token Debugger* and click *Extend Access Token*.
7. Copy `.env.example` to `.env`, paste the two values in, and run `insta_post.py --check`.
   `.env` is in `.gitignore`, so never paste the token anywhere else.

Limits: MP4/MOV, 3 s to 15 min, 300 MB max. Vertical 1080x1920 looks best.
A song baked into the video isn't Instagram's licensed music, and copyrighted tracks can get a reel muted. Instagram's own music can only be added in the Instagram app.
