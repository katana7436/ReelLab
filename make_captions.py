r"""
make_captions.py - speech to subtitles with faster-whisper (runs on CPU).

  python make_captions.py output\\reel_preview.mp4            # writes .srt next to the video
  python make_captions.py raw\\vlog.mp4 --burn               # also burns big centred captions in
  python make_captions.py raw\\vlog.mp4 --lang hi --model medium

Models: tiny / base / small (default, good on a laptop) / medium (better Hindi, slow).
"""
import reellab_paths  # noqa: F401  puts the bundled ffmpeg on PATH
import argparse, subprocess
from pathlib import Path
from faster_whisper import WhisperModel


def ts(t):
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h:02d}:{m:02d}:{t % 60:06.3f}".replace(".", ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default="small")
    ap.add_argument("--lang", default=None, help="en, hi, ... (auto if omitted)")
    ap.add_argument("--burn", action="store_true")
    ap.add_argument("--words", type=int, default=3, help="max words per caption (short = reel style)")
    a = ap.parse_args()

    v = Path(a.video)
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, info = model.transcribe(str(v), language=a.lang, vad_filter=True, word_timestamps=True)
    print(f"language: {info.language}")
    chunks = []
    for s in segs:
        words = list(s.words or [])
        for i in range(0, len(words), a.words):
            grp = words[i:i + a.words]
            chunks.append((grp[0].start, grp[-1].end, " ".join(w.word.strip() for w in grp)))
    srt = v.with_suffix(".srt")
    srt.write_text("".join(f"{i}\n{ts(s)} --> {ts(e)}\n{t}\n\n" for i, (s, e, t) in enumerate(chunks, 1)),
                   encoding="utf-8")
    print(f"wrote {srt}")
    if a.burn:
        out = v.with_name(v.stem + "_captioned.mp4")
        sub = str(srt.resolve()).replace("\\", "/").replace(":", "\\:")
        style = "Fontname=Arial,Fontsize=16,Bold=1,Outline=2,Shadow=0,Alignment=2,MarginV=60"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(v), "-vf",
                        f"subtitles='{sub}':force_style='{style}'", "-c:a", "copy",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)], check=True)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
