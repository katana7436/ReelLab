r"""
analyze_style.py - learn the editing style of reference videos.

  python analyze_style.py                 # analyse everything in reference\
  python analyze_style.py --no-whisper    # skip speech transcription (faster)

For each video in reference\ it measures:
  - pacing: shot lengths (median / fast / slow), cuts per second, pacing over time
  - beat sync: how often cuts land on a music beat
  - colour: brightness, contrast, saturation, warmth + colour statistics
            used later to build a matching LUT for YOUR footage
  - speech: what is said (faster-whisper), if anything
  - a contact sheet (one frame per shot) so Claude can look at the framing

Writes reference\_analysis\style.json (combined profile used by autocut.py --style)
       reference\_analysis\<video>_sheet.jpg
       reference\_analysis\<video>.json
"""
import argparse, json, subprocess, sys
from pathlib import Path

import cv2
import numpy as np

from reellab_paths import ROOT, DATA   # also puts the bundled ffmpeg on PATH
REF = DATA / "reference"
OUT = REF / "_analysis"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def shots_of(path):
    from scenedetect import detect, ContentDetector
    scenes = detect(str(path), ContentDetector(threshold=27))
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    rng = [(float(s.get_seconds()), float(e.get_seconds())) for s, e in scenes] or [(0.0, dur)]
    return rng, cap, fps, dur, w, h


def colour_stats(cap, fps, ranges):
    """Sample 3 frames per shot; return look metrics + RGB mean/cov for LUT matching."""
    px, mids = [], []
    for t0, t1 in ranges:
        for f in (0.25, 0.5, 0.75):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((t0 + (t1 - t0) * f) * fps))
            ok, fr = cap.read()
            if not ok:
                continue
            if f == 0.5:
                mids.append(fr)
            small = cv2.resize(fr, (96, 54), interpolation=cv2.INTER_AREA)
            px.append(small[:, :, ::-1].reshape(-1, 3) / 255.0)     # BGR->RGB
    px = np.concatenate(px) if px else np.zeros((1, 3))
    hsv = cv2.cvtColor((px.reshape(-1, 1, 3)[:, :, ::-1] * 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
    luma = px @ np.array([0.2126, 0.7152, 0.0722])
    look = dict(
        brightness=round(float(luma.mean()), 3),
        contrast=round(float(luma.std()), 3),
        saturation=round(float(hsv[:, 0, 1].mean() / 255), 3),
        warmth=round(float(px[:, 0].mean() - px[:, 2].mean()), 3),     # +warm / -cool
        shadows=round(float(np.percentile(luma, 5)), 3),
        highlights=round(float(np.percentile(luma, 95)), 3),
    )
    return look, px.mean(0).tolist(), np.cov(px.T).tolist(), mids


def beat_sync(path, cuts):
    import librosa, tempfile, os
    wav = Path(tempfile.gettempdir()) / "ref_audio.wav"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", "22050", str(wav)])
    if r.returncode or not wav.exists():
        return None, None
    y, sr = librosa.load(str(wav), sr=22050, mono=True)
    os.remove(wav)
    if y.size < sr or np.abs(y).max() < 1e-3:
        return None, None
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    bt = librosa.frames_to_time(beats, sr=sr)
    if len(bt) == 0 or not cuts:
        return float(np.atleast_1d(tempo)[0]), None
    hits = sum(np.min(np.abs(bt - c)) < 0.09 for c in cuts)
    return round(float(np.atleast_1d(tempo)[0]), 1), round(hits / len(cuts), 2)


def transcribe(path):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, info = model.transcribe(str(path), vad_filter=True)
    text = [dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()) for s in segs]
    return dict(language=info.language, segments=text) if text else None


def contact_sheet(mids, out):
    if not mids:
        return
    thumbs = [cv2.resize(m, (180, int(180 * m.shape[0] / m.shape[1]))) for m in mids[:40]]
    th = max(t.shape[0] for t in thumbs)
    thumbs = [cv2.copyMakeBorder(t, 0, th - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in thumbs]
    cols = 8
    while len(thumbs) % cols:
        thumbs.append(np.zeros_like(thumbs[0]))
    rows = [np.hstack(thumbs[i:i + cols]) for i in range(0, len(thumbs), cols)]
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def analyse(path, use_whisper):
    print(f"\n== {path.name}")
    ranges, cap, fps, dur, w, h = shots_of(path)
    lens = np.array([b - a for a, b in ranges])
    cuts = [a for a, _ in ranges[1:]]
    thirds = [lens[[i for i, (a, _) in enumerate(ranges) if dur * k / 3 <= a < dur * (k + 1) / 3]]
              for k in range(3)]
    pacing = dict(
        shots=len(ranges), duration=round(dur, 2), cuts_per_sec=round(len(cuts) / dur, 2) if dur else 0,
        median_shot=round(float(np.median(lens)), 2),
        fast_shot=round(float(np.percentile(lens, 20)), 2),
        slow_shot=round(float(np.percentile(lens, 90)), 2),
        median_by_third=[round(float(np.median(t)), 2) if len(t) else None for t in thirds],
    )
    look, mean, cov, mids = colour_stats(cap, fps, ranges)
    cap.release()
    tempo, sync = beat_sync(path, cuts)
    res = dict(file=path.name, width=w, height=h, fps=round(fps, 2),
               vertical=h > w, pacing=pacing, look=look,
               music=dict(tempo=tempo, cuts_on_beat=sync),
               colour=dict(mean=mean, cov=cov))
    if use_whisper:
        print("   transcribing speech...")
        res["speech"] = transcribe(path)
    contact_sheet(mids, OUT / f"{path.stem}_sheet.jpg")
    (OUT / f"{path.stem}.json").write_text(json.dumps(res, indent=1))
    print(f"   {pacing['shots']} shots, median {pacing['median_shot']}s, "
          f"{pacing['cuts_per_sec']} cuts/s, on-beat {sync}, look {look}")
    return res


def combine(results):
    def med(key, sub):
        v = [r[sub][key] for r in results if r[sub].get(key) is not None]
        return round(float(np.median(v)), 3) if v else None
    n = len(results)
    mean = np.mean([r["colour"]["mean"] for r in results], 0)
    cov = np.mean([r["colour"]["cov"] for r in results], 0)
    return dict(
        references=[r["file"] for r in results],
        pacing={k: med(k, "pacing") for k in
                ("duration", "cuts_per_sec", "median_shot", "fast_shot", "slow_shot")},
        intro_faster=all((r["pacing"]["median_by_third"][0] or 99) < 0.85 * (r["pacing"]["median_shot"] or 0)
                         for r in results),
        look={k: med(k, "look") for k in results[0]["look"]},
        music=dict(tempo=med("tempo", "music"), cuts_on_beat=med("cuts_on_beat", "music")),
        has_speech=any(r.get("speech") for r in results),
        vertical=sum(r["vertical"] for r in results) >= n / 2,
        colour=dict(mean=mean.tolist(), cov=cov.tolist()),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-whisper", action="store_true")
    ap.add_argument("--trip", default=None, help="subfolder of reference\\ e.g. himachal")
    a = ap.parse_args()
    global REF, OUT
    if a.trip:
        REF = DATA / "reference" / a.trip
        OUT = REF / "_analysis"
    vids = sorted(p for p in REF.iterdir() if p.suffix.lower() in VIDEO_EXT) if REF.exists() else []
    if not vids:
        sys.exit("No videos in reference\\ - run FETCH_REFS.bat or drop files in.")
    OUT.mkdir(parents=True, exist_ok=True)
    results = [analyse(v, not a.no_whisper) for v in vids]
    style = combine(results)
    (OUT / "style.json").write_text(json.dumps(style, indent=1))
    p, l = style["pacing"], style["look"]
    print("\n==== STYLE PROFILE ====")
    print(f"length ~{p['duration']}s | median shot {p['median_shot']}s "
          f"(fast {p['fast_shot']}s, hero {p['slow_shot']}s) | {p['cuts_per_sec']} cuts/s")
    print(f"cuts on beat: {style['music']['cuts_on_beat']} | intro faster: {style['intro_faster']}")
    print(f"look: bright {l['brightness']} contrast {l['contrast']} sat {l['saturation']} warmth {l['warmth']}")
    print("saved reference\\_analysis\\style.json  ->  python autocut.py --style")


if __name__ == "__main__":
    main()
