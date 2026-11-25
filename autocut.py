r"""
autocut.py - beat-synced fast-cut reel builder for travel footage.

  python autocut.py                      # 30s reel, defaults
  python autocut.py --length 20 --lut luts\teal_orange.cube
  python autocut.py --no-preview         # only the Resolve timeline (fast)
  python autocut.py --style              # copy pacing + colour of reference\ videos
                                         # (run analyze_style.py first)

Reads   raw\    video clips (mp4/mov/mkv)
        music\  one audio file (first one found is used)
        luts\   optional .cube LUT (pass with --lut)
Writes  output\reel_preview.mp4   1080x1920 preview with music
        output\reel_timeline.fcpxml  import into DaVinci Resolve:
                File > Import > Timeline > select the .fcpxml
        output\shots.json         every detected shot with its score
"""
import argparse, json, subprocess, sys, shutil
from pathlib import Path

import cv2
import numpy as np
import librosa
from scenedetect import detect, ContentDetector

ROOT = Path(__file__).resolve().parent
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".avi"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
FPS = 30
W, H = 1080, 1920


# ---------- shot detection + scoring ----------
def score_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bright = gray.mean() / 255.0                      # 0..1
    sharp = cv2.Laplacian(gray, cv2.CV_64F).var()     # higher = sharper
    return bright, sharp


def shake_score(cap, t0, t1, src_fps):
    """Mean optical-flow jitter between a few frames; higher = shakier."""
    pts = np.linspace(t0, t1, 5)
    prev, mags = None, []
    for t in pts:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * src_fps))
        ok, f = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(f, (320, 180)), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            flow = cv2.calcOpticalFlowFarneback(prev, g, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mags.append(np.linalg.norm(flow, axis=2).std())
        prev = g
    return float(np.mean(mags)) if mags else 0.0


PIXELS = []   # downsampled RGB samples of your footage, for colour matching


SRC = ROOT / "raw"
OUTDIR = ROOT / "output"


def find_shots(min_len):
    clips = sorted(p for p in SRC.rglob("*") if p.suffix.lower() in VIDEO_EXT
                   and "live_photos" not in p.parts and "_to_delete" not in p.parts)
    if not clips:
        sys.exit("No clips in raw\\ - add your footage first.")
    shots = []
    for ci, clip in enumerate(clips):
        print(f"  scanning {clip.name}")
        cap = cv2.VideoCapture(str(clip))
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / src_fps
        scenes = detect(str(clip), ContentDetector(threshold=27))
        ranges = [(s.get_seconds(), e.get_seconds()) for s, e in scenes] or [(0.0, dur)]
        for (t0, t1) in ranges:
            if t1 - t0 < min_len:
                continue
            mid = (t0 + t1) / 2
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid * src_fps))
            ok, frame = cap.read()
            if not ok:
                continue
            bright, sharp = score_frame(frame)
            PIXELS.append(cv2.resize(frame, (96, 54), interpolation=cv2.INTER_AREA)[:, :, ::-1]
                          .reshape(-1, 3) / 255.0)
            shake = shake_score(cap, t0, t1, src_fps)
            shots.append(dict(file=str(clip), clip_index=ci, start=float(t0), end=float(t1),
                              src_fps=float(src_fps), bright=float(bright), sharp=float(sharp), shake=shake,
                              w=frame.shape[1], h=frame.shape[0]))
        cap.release()
    if not shots:
        sys.exit("No usable shots found (all too short?). Try --min-shot 0.5")
    # normalise and score
    sh = np.array([s["sharp"] for s in shots]); sh = sh / (sh.max() or 1)
    jk = np.array([s["shake"] for s in shots]); jk = jk / (jk.max() or 1)
    for s, a, b in zip(shots, sh, jk):
        exposure = 1 - abs(s["bright"] - 0.5) * 2        # best at mid-grey
        s["score"] = round(float(0.45 * a + 0.35 * exposure + 0.20 * (1 - b)), 4)
        s["reject"] = bool(s["bright"] < 0.12 or s["bright"] > 0.93)
    return shots


# ---------- music ----------
def beat_slots(music, length, target_shot=0.8, hero_len=None, intro_faster=False):
    y, sr = librosa.load(str(music), sr=22050, mono=True, duration=length + 5)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    times = librosa.frames_to_time(beats, sr=sr)
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    strength = onset[np.clip(beats, 0, len(onset) - 1)]
    # cut every N beats so shots land around 0.5-1.5 s
    beat = 60 / tempo
    step = max(1, round(target_shot / beat))
    if intro_faster and step > 1:      # reference opens faster: double cut rate in first 3 s
        early = [t for t in times if t < 3.0]
        cuts = list(early[::max(1, step // 2)]) + list([t for t in times if t >= 3.0][::step])
    else:
        cuts = list(times[::step])
    cuts = [t for t in cuts if t < length] + [length]
    if cuts[0] > 0.05:
        cuts = [0.0] + cuts
    # "drop" = strongest beat after the first quarter -> gets a long hero shot
    mask = times > length * 0.25
    drop_t = float(times[mask][np.argmax(strength[mask])]) if mask.any() else None
    slots = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        slots.append([a, b])
    if drop_t is not None:
        for i, (a, b) in enumerate(slots):
            if a <= drop_t < b or abs(a - drop_t) < 0.05:
                hero_end = min(length, a + (hero_len or 4 * beat))
                j = i
                while j + 1 < len(slots) and slots[j + 1][1] <= hero_end:
                    j += 1
                slots[i:j + 1] = [[a, slots[j][1]]]
                slots[i].append("hero")
                break
    print(f"  tempo {tempo:.0f} BPM, cutting every {step} beat(s), {len(slots)} shots")
    return slots, tempo, [round(float(t), 3) for t in times if t <= length]


# ---------- assignment ----------
def assign(shots, slots):
    usable = [s for s in shots if not s["reject"]] or shots
    hero = max(usable, key=lambda s: s["score"])
    pool = sorted([s for s in usable if s is not hero], key=lambda s: -s["score"])
    need = len(slots) - 1
    picked = pool[:need]
    picked.sort(key=lambda s: (s["clip_index"], s["start"]))   # keep trip order
    timeline = []
    for slot in slots:
        a, b = slot[0], slot[1]
        d = b - a
        if len(slot) > 2:
            shot = hero
        else:
            if not picked:
                picked = sorted(pool, key=lambda s: (s["clip_index"], s["start"]))
            # next shot (in trip order) that is long enough for this slot
            fit = next((x for x in picked if x["end"] - x["start"] >= d), None)
            if fit is None:
                fit = max(pool, key=lambda x: x["end"] - x["start"])
            else:
                picked.remove(fit)
            shot = fit
        length = shot["end"] - shot["start"]
        d_use = min(d, length)
        src_in = shot["start"] + (length - d_use) / 2   # take the middle of the shot
        timeline.append(dict(file=shot["file"], src_in=src_in, dur=d_use, rec_in=a,
                             hero=len(slot) > 2, src_fps=shot["src_fps"],
                             w=shot["w"], h=shot["h"],
                             shot_start=shot["start"], shot_end=shot["end"], score=shot["score"]))
    return timeline


# ---------- colour match (MKL transfer -> .cube LUT) ----------
def _sqrtm(m):
    w, v = np.linalg.eigh((m + m.T) / 2)
    return (v * np.sqrt(np.clip(w, 1e-10, None))) @ v.T


def build_match_lut(style, out, strength=0.75, size=33):
    """Fit a linear colour transform from YOUR footage to the reference look and save as .cube."""
    src = np.concatenate(PIXELS)
    mu_s, cs = src.mean(0), np.cov(src.T) + np.eye(3) * 1e-6
    mu_r = np.array(style["colour"]["mean"]); cr = np.array(style["colour"]["cov"]) + np.eye(3) * 1e-6
    cs_h = _sqrtm(cs); cs_hi = np.linalg.inv(cs_h)
    T = cs_hi @ _sqrtm(cs_h @ cr @ cs_h) @ cs_hi
    g = np.linspace(0, 1, size)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # .cube order: R fastest
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    mapped = (rgb - mu_s) @ T + mu_r
    mapped = np.clip(rgb + strength * (mapped - rgb), 0, 1)
    with open(out, "w") as f:
        f.write(f'TITLE "match reference"\nLUT_3D_SIZE {size}\n')
        f.writelines(f"{x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in mapped)
    return out


# ---------- outputs ----------
def frames(t):
    return int(round(t * FPS))


def write_fcpxml(timeline, music, out, name="ReelLab"):
    from xml.sax.saxutils import quoteattr, escape
    name = escape(name, {'"': "&quot;"})
    def r(t):  # rational time in FPS frames
        return f"{frames(t)}/{FPS}s"
    files = sorted({c["file"] for c in timeline} | {str(music)})
    assets = []
    for i, f in enumerate(files):
        uri = Path(f).resolve().as_uri()
        is_audio = Path(f).suffix.lower() in AUDIO_EXT
        assets.append(
            f'    <asset id="a{i}" name={quoteattr(Path(f).name)} start="0s" duration="3600s" '
            f'hasVideo="{0 if is_audio else 1}" hasAudio="1" format="r1">\n'
            f'      <media-rep kind="original-media" src={quoteattr(uri)}/>\n    </asset>')
    aid = {f: f"a{i}" for i, f in enumerate(files)}
    total = timeline[-1]["rec_in"] + timeline[-1]["dur"]
    spine = []
    for n, c in enumerate(timeline):
        music_child = ""
        if n == 0:
            music_child = (f'\n          <asset-clip ref="{aid[str(music)]}" lane="-1" offset="0s" '
                           f'start="0s" duration="{r(total)}" name="music" audioRole="music"/>\n        ')
        spine.append(
            f'        <asset-clip ref="{aid[c["file"]]}" offset="{r(c["rec_in"])}" '
            f'start="{r(c["src_in"])}" duration="{r(c["dur"])}" '
            f'name={quoteattr(Path(c["file"]).name + (" HERO" if c["hero"] else ""))}>'
            f'{music_child}</asset-clip>')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
  <resources>
    <format id="r1" name="FFVideoFormat{W}x{H}p{FPS}" frameDuration="1/{FPS}s" width="{W}" height="{H}"/>
{chr(10).join(assets)}
  </resources>
  <library>
    <event name="{name}">
      <project name="{name} Reel">
        <sequence format="r1" duration="{r(total)}" tcStart="0s" tcFormat="NDF">
          <spine>
{chr(10).join(spine)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''
    out.write_text(xml, encoding="utf-8")


def render_preview(timeline, music, lut, out):
    tmp = OUTDIR / "_parts"
    tmp.mkdir(parents=True, exist_ok=True)
    vf_base = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               f"fps={FPS},setsar=1")
    if lut:
        lut_path = str(Path(lut).resolve()).replace("\\", "/").replace(":", "\\:")
        vf_base += f",lut3d='{lut_path}'"
    parts = []
    for i, c in enumerate(timeline):
        p = tmp / f"p{i:03d}.mp4"
        vf = vf_base + (",eq=saturation=1.08:contrast=1.04" if c["hero"] else "")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{c['src_in']:.3f}",
               "-i", c["file"], "-t", f"{c['dur']:.3f}", "-an", "-vf", vf,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(p)]
        subprocess.run(cmd, check=True)
        parts.append(p)
        print(f"  rendered {i+1}/{len(timeline)}", end="\r")
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    total = timeline[-1]["rec_in"] + timeline[-1]["dur"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-i", str(music), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", f"afade=t=out:st={max(0, total-1.0):.2f}:d=1",
                    "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--length", type=float, default=None, help="reel length in seconds (default 30, or the reference length)")
    ap.add_argument("--lut", help="path to a .cube LUT for the preview")
    ap.add_argument("--min-shot", type=float, default=0.8, help="ignore shots shorter than this")
    ap.add_argument("--no-preview", action="store_true", help="skip rendering the MP4")
    ap.add_argument("--style", nargs="?", const=str(ROOT / "reference" / "_analysis" / "style.json"),
                    help="copy pacing + colour from analyze_style.py output")
    ap.add_argument("--trip", default=None, help="subfolder of raw\\ and reference\\ e.g. himachal")
    ap.add_argument("--orientation", choices=["horizontal", "vertical"], default=None)
    ap.add_argument("--match-strength", type=float, default=0.75, help="0-1, how hard to copy the colour")
    a = ap.parse_args()
    global SRC, OUTDIR
    if a.trip:
        SRC = ROOT / "raw" / a.trip
        OUTDIR = ROOT / "output" / a.trip
        if a.style == str(ROOT / "reference" / "_analysis" / "style.json"):
            a.style = str(ROOT / "reference" / a.trip / "_analysis" / "style.json")
    if a.orientation:
        SRC = SRC / a.orientation

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found - run setup.ps1 first.")
    music = next((p for p in sorted((ROOT / "music").iterdir()) if p.suffix.lower() in AUDIO_EXT), None)
    if not music:
        sys.exit("No song in music\\ - add one audio file.")
    OUTDIR.mkdir(parents=True, exist_ok=True)

    style = None
    if a.style:
        sp = Path(a.style)
        if not sp.exists():
            sys.exit("No style profile - run analyze_style.py first.")
        style = json.loads(sp.read_text())
        print(f"Copying style of: {', '.join(style['references'])}")
    length = a.length or (min(60, style["pacing"]["duration"]) if style and style["pacing"]["duration"] else 30)

    print("1/4 finding shots..."); shots = find_shots(a.min_shot)
    (OUTDIR / "shots.json").write_text(json.dumps(shots, indent=1))
    print(f"  {len(shots)} shots, {sum(s['reject'] for s in shots)} rejected (too dark/bright)")
    lut = a.lut
    if style:
        lut = build_match_lut(style, OUTDIR / "match_reference.cube", a.match_strength)
        print("  built output\\match_reference.cube (also usable in Resolve)")
        p = style["pacing"]
        print("2/4 reading the beat..."); slots, tempo, beats = beat_slots(
            music, length, target_shot=p["median_shot"] or 0.8,
            hero_len=p["slow_shot"], intro_faster=style.get("intro_faster", False))
    else:
        print("2/4 reading the beat..."); slots, tempo, beats = beat_slots(music, length)
    print("3/4 building timeline..."); tl = assign(shots, slots)
    name = a.trip.capitalize() if a.trip else "ReelLab"
    write_fcpxml(tl, music, OUTDIR / "reel_timeline.fcpxml", name=name)
    print("  wrote output\\reel_timeline.fcpxml")
    # editable copy of the cut for editor.py (open it there to swap / trim / reorder shots)
    (OUTDIR / "timeline.json").write_text(json.dumps(dict(
        name=name, music=str(music), lut=str(lut) if lut else None, fps=FPS,
        tempo=round(tempo, 1), beats=beats, clips=tl), indent=1))
    print("  wrote output\\timeline.json  (python editor.py to edit it)")
    if not a.no_preview:
        print("4/4 rendering preview (slow on integrated graphics - be patient)...")
        render_preview(tl, music, lut, OUTDIR / "reel_preview.mp4")
        print("\n  wrote output\\reel_preview.mp4")
    print("Done.")


if __name__ == "__main__":
    main()
