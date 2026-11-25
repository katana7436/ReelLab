r"""
import_video.py - turn a finished video into an editable timeline for editor.py.

  python import_video.py output\himachal\Himachal_ref2_v2.mp4
  python import_video.py some.mp4 --name my_edit

A rendered MP4 has no timeline inside it, so this detects its cuts and makes one clip per cut.
The source of every clip is the video itself, and its own soundtrack becomes the music.
In the editor you can then reorder, trim, split, delete and re-render. Titles that are part of
the picture stay in the picture.

Writes output\<name>\timeline.json + shots.json   (name defaults to the video's file name)
The video itself is only read.
"""
import argparse, json, re, sys
from pathlib import Path

import cv2
from scenedetect import detect, ContentDetector

from reellab_paths import ROOT, DATA   # also puts the bundled ffmpeg on PATH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--name", help="folder name under output\\ (default: video file name)")
    ap.add_argument("--threshold", type=float, default=27, help="cut sensitivity, lower = more cuts")
    ap.add_argument("--force", action="store_true", help="overwrite an existing timeline of that name")
    a = ap.parse_args()

    v = Path(a.video).resolve()
    if not v.exists():
        sys.exit(f"not found: {v}")
    name = a.name or re.sub(r"[^A-Za-z0-9_-]+", "_", v.stem).lower()
    out = DATA / "output" / name
    if (out / "timeline.json").exists() and not a.force:
        sys.exit(f"{out}\\timeline.json already exists - add --force to start over (your edits there would be lost)")

    cap = cv2.VideoCapture(str(v))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    print(f"finding cuts in {v.name} ({w}x{h}, {dur:.1f}s)...")
    scenes = detect(str(v), ContentDetector(threshold=a.threshold))
    ranges = [(s.get_seconds(), e.get_seconds()) for s, e in scenes] or [(0.0, dur)]

    shots, clips, pos = [], [], 0.0
    for i, (t0, t1) in enumerate(ranges):
        t0, t1 = round(float(t0), 3), round(float(t1), 3)
        if t1 - t0 <= 0:
            continue
        shot = dict(file=str(v), clip_index=0, start=t0, end=t1, src_fps=float(fps),
                    w=w, h=h, score=0.5, reject=False)
        shots.append(shot)
        clips.append(dict(file=str(v), src_in=t0, dur=round(t1 - t0, 3), rec_in=round(pos, 3), hero=False,
                          src_fps=float(fps), w=w, h=h, shot_start=t0, shot_end=t1, score=0.5))
        pos += t1 - t0

    out.mkdir(parents=True, exist_ok=True)
    # size = output frame; the editor and renders keep the video's own shape (e.g. 16:9)
    (out / "timeline.json").write_text(json.dumps(dict(
        name=v.stem, music=str(v), lut=None, fps=round(fps), size=[w, h], tempo=None, beats=[],
        imported_from=str(v), clips=clips), indent=1), encoding="utf-8")
    (out / "shots.json").write_text(json.dumps(shots, indent=1), encoding="utf-8")
    print(f"{len(clips)} clips -> {out}\\timeline.json")
    print("open it with START_EDITOR.bat (or python editor.py)")


if __name__ == "__main__":
    main()
