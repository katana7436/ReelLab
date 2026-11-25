r"""
selftest.py - checks that ReelLab works on this computer (Windows, macOS or Linux).

  python selftest.py          (INSTALL runs this for you at the end)

Makes a few synthetic test clips and a beat track in a temporary folder, then runs the
real pipeline on them: autocut (shot detection, beat sync, render), analyze_style +
autocut --style (colour match LUT), import_video, the timeline editor's web server,
and the captions engine import. Your own raw/, music/ and output/ folders are not touched.
Prints PASS/FAIL per step; exit code 0 only if everything passed.
"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, traceback, urllib.request
from pathlib import Path

from reellab_paths import ROOT, INSTALL_HINT   # puts the bundled ffmpeg on PATH

PY = sys.executable
RESULTS = []


def step(name):
    def wrap(fn):
        def run(*a):
            t0 = time.time()
            try:
                detail = fn(*a) or ""
                RESULTS.append((name, True, detail))
                print(f"PASS  {name:<28} {detail}  ({time.time() - t0:.0f}s)", flush=True)
            except Exception as e:
                RESULTS.append((name, False, str(e)))
                print(f"FAIL  {name:<28} {e}", flush=True)
                if os.environ.get("REELLAB_DEBUG"):
                    traceback.print_exc()
        return run
    return wrap


def sh(cmd, env=None, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout, cwd=ROOT,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"{Path(cmd[1]).name if cmd[0] == PY else cmd[0]} exited {r.returncode}: "
                           + (r.stderr or r.stdout).strip()[-600:])
    return r.stdout


def probe(p):
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
              "-of", "json", str(p)])
    j = json.loads(out)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    return float(j["format"]["duration"]), v["width"], v["height"], any(s["codec_type"] == "audio" for s in j["streams"])


def main():
    print(f"ReelLab self-test  |  Python {sys.version.split()[0]}  |  {sys.platform}  |  {ROOT}\n")
    home = Path(tempfile.mkdtemp(prefix="reellab_test_"))
    env = dict(os.environ, REELLAB_HOME=str(home), PYTHONIOENCODING="utf-8")
    raw = home / "raw" / "test"
    raw.mkdir(parents=True)
    out = home / "output" / "test"
    try:
        tools(); libs()
        make_media(raw, home)
        autocut(env, out, home)
        style(env, out, home)
        importer(env, out, home)
        editor(env, home)
        captions()
    finally:
        shutil.rmtree(home, ignore_errors=True)
    bad = [n for n, ok, _ in RESULTS if not ok]
    print("\n" + ("ALL CHECKS PASSED - ReelLab is ready." if not bad else f"{len(bad)} CHECK(S) FAILED: {', '.join(bad)}"))
    return 1 if bad else 0


@step("ffmpeg + ffprobe")
def tools():
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            raise RuntimeError(f"{t} not found - {INSTALL_HINT}")
    return sh(["ffmpeg", "-version"]).splitlines()[0][:60]


@step("python libraries")
def libs():
    import cv2, librosa, numpy, scenedetect, soundfile  # noqa: F401
    return f"opencv {cv2.__version__}, librosa {librosa.__version__}, scenedetect {scenedetect.__version__}"


@step("make test clips + beat track")
def make_media(raw, home):
    # four different-looking vertical clips (each one is a separate "shot") + a 120 bpm click track
    srcs = ["testsrc2=s=540x960:r=30", "smptehdbars=s=540x960:r=30",
            "mandelbrot=s=540x960:r=30", "life=s=540x960:r=30:mold=10:ratio=0.5:death_color=#2050a0:life_color=#ffd060"]
    for i, s in enumerate(srcs):
        sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", s, "-t", "3", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", str(raw / f"clip{i}.mp4")])
    (home / "music").mkdir()
    sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "aevalsrc=0.8*sin(2*PI*90*t)*exp(-25*mod(t\\,0.5))+0.2*sin(2*PI*440*t)*exp(-8*mod(t\\,2)):s=44100:d=14",
        str(home / "music" / "beat.wav")])
    return "4 clips, 14s beat"


@step("autocut (beat-synced reel)")
def autocut(env, out, home):
    sh([PY, "autocut.py", "--trip", "test", "--length", "8", "--min-shot", "0.5"], env)
    dur, w, h, audio = probe(out / "reel_preview.mp4")
    tl = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    if (w, h) != (1080, 1920) or not audio or abs(dur - 8) > 1.0:
        raise RuntimeError(f"preview is {w}x{h}, {dur:.1f}s, audio={audio}")
    if not (out / "reel_timeline.fcpxml").exists():
        raise RuntimeError("no FCPXML written")
    return f"{len(tl['clips'])} clips, {dur:.1f}s 1080x1920, tempo {tl.get('tempo', 0):.0f}"


@step("analyze_style + --style")
def style(env, out, home):
    ref = home / "reference" / "test"
    ref.mkdir(parents=True)
    shutil.copy(out / "reel_preview.mp4", ref / "ref.mp4")
    sh([PY, "analyze_style.py", "--trip", "test", "--no-whisper"], env)
    if not (ref / "_analysis" / "style.json").exists():
        raise RuntimeError("no style.json")
    sh([PY, "autocut.py", "--trip", "test", "--style", "--no-preview", "--length", "8", "--min-shot", "0.5"], env)
    if not (out / "match_reference.cube").exists():
        raise RuntimeError("no colour-match LUT")
    return "style.json + match_reference.cube"


@step("import_video")
def importer(env, out, home):
    sh([PY, "import_video.py", str(out / "reel_preview.mp4"), "--name", "imported"], env)
    tl = json.loads((home / "output" / "imported" / "timeline.json").read_text(encoding="utf-8"))
    return f"{len(tl['clips'])} clips found"


@step("timeline editor server")
def editor(env, home):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    p = subprocess.Popen([PY, "editor.py", "--port", str(port)], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                trips = json.load(urllib.request.urlopen(base + "/api/trips", timeout=2))["trips"]
                break
            except OSError:
                if p.poll() is not None:
                    raise RuntimeError("editor stopped: " + p.stderr.read()[-400:])
                time.sleep(0.5)
        else:
            raise RuntimeError("editor did not start")
        if "test" not in trips:
            raise RuntimeError(f"trips = {trips}")
        tl = json.load(urllib.request.urlopen(base + "/api/timeline?trip=test", timeout=10))["timeline"]
        c = tl["clips"][0]
        q = urllib.parse.urlencode(dict(trip="test", file=c["file"], t=c["src_in"]))
        img = urllib.request.urlopen(base + "/thumb?" + q, timeout=120).read()
        page = urllib.request.urlopen(base + "/", timeout=10).read()
        if img[:2] != b"\xff\xd8" or b"<html" not in page.lower():
            raise RuntimeError("thumbnail or page broken")
        return f"page + API + thumbnail OK on port {port}"
    finally:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


@step("captions engine")
def captions():
    import faster_whisper
    return f"faster-whisper {faster_whisper.__version__} (model downloads on first use)"


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used in editor step)
    sys.exit(main())
