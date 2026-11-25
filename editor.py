r"""
editor.py - browser timeline editor for reels made by autocut.py.

  python editor.py                 # then open http://127.0.0.1:8765
  python editor.py --port 9000
  python editor.py --out D:\somewhere\output   # edit timelines in another output folder

Reads   output\<trip>\timeline.json   (written by autocut.py)
        output\<trip>\shots.json      (every shot autocut found = the swap pool)
Writes  output\<trip>\timeline.json   (your edits; previous version kept as timeline.prev.json)
        output\<trip>\reel_timeline.fcpxml   (re-made on every save, import into Resolve)
        output\<trip>\reel_preview.mp4       (when you press Render)
        output\<trip>\_editor_cache\         (small thumbnails + low-res preview clips, safe to delete)

Only runs on this computer (127.0.0.1). Raw footage is only read, never changed.
"""
import argparse, hashlib, json, mimetypes, os, re, shutil, subprocess, sys, threading, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from reellab_paths import ROOT, DATA, INSTALL_HINT   # also puts the bundled ffmpeg on PATH
UI = ROOT / "editor" / "index.html"
OUT = DATA / "output"
FFMPEG_SLOTS = threading.Semaphore(3)      # max parallel ffmpeg jobs (4K HEVC decode is heavy)
RENDER = dict(state="idle", msg="", trip=None)
POST = dict(state="idle", msg="", link=None)   # Instagram upload progress
AUTOCUT_LOCK = threading.Lock()   # autocut's frame size is a module global; one user at a time


# ---------- helpers ----------
def trip_dir(trip):
    d = (OUT / trip).resolve()
    if d.parent != OUT.resolve() or not (d / "timeline.json").exists():
        raise ValueError(f"no timeline for trip '{trip}'")
    return d


def load_json(p, default=None):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


def allowed_files(d):
    """Only media referenced by this trip's timeline / shot list may be read."""
    tl = load_json(d / "timeline.json", {})
    files = {c["file"] for c in tl.get("clips", [])}
    files |= {s["file"] for s in load_json(d / "shots.json", [])}
    if tl.get("music"):
        files.add(tl["music"])
    return {str(Path(f).resolve()).lower() for f in files}


def check_file(d, f):
    if str(Path(f).resolve()).lower() not in allowed_files(d):
        raise PermissionError("file not part of this timeline")
    return f


def ff_filter_path(p):
    return str(Path(p).resolve()).replace("\\", "/").replace(":", "\\:")


def cached_ffmpeg(cache, key, ext, build_cmd):
    """Run ffmpeg once per key; return the cached output path."""
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / (hashlib.md5(key.encode()).hexdigest()[:16] + ext)
    if out.exists() and out.stat().st_size > 0:
        return out
    tmp = out.with_name(out.stem + ".tmp" + ext)
    with FFMPEG_SLOTS:
        if out.exists() and out.stat().st_size > 0:
            return out
        r = subprocess.run(build_cmd(tmp), capture_output=True, text=True)
        if r.returncode or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ffmpeg failed: " + r.stderr.strip()[-300:])
        os.replace(tmp, out)
    return out


def frame_size(tl):
    """Output frame of this timeline: 1080x1920 for autocut reels, the video's own size for imports."""
    w, h = (tl or {}).get("size") or (1080, 1920)
    return int(w), int(h)


def small(size, long_side):
    w, h = size
    k = long_side / max(w, h)
    return 2 * round(w * k / 2), 2 * round(h * k / 2)


def fill_crop(w, h):
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def thumb(d, f, t, size):
    t = max(0.0, float(t))
    vf = fill_crop(*small(size, 320))
    return cached_ffmpeg(d / "_editor_cache" / "thumbs", f"{f}|{t:.2f}|{vf}", ".jpg", lambda o: [
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", f, "-frames:v", "1",
        "-vf", vf, "-q:v", "5", str(o)])


def proxy(d, f, t, dur, hero, lut, size):
    """Low-res clip of exactly what the reel will show (same crop, LUT, hero boost)."""
    t, dur = max(0.0, float(t)), max(0.05, float(dur))
    vf = fill_crop(*small(size, 640)) + ",fps=30"
    if lut and Path(lut).exists():
        vf += f",lut3d='{ff_filter_path(lut)}'"
    if hero:
        vf += ",eq=saturation=1.08:contrast=1.04"
    return cached_ffmpeg(d / "_editor_cache" / "proxies", f"{f}|{t:.3f}|{dur:.3f}|{vf}", ".mp4", lambda o: [
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", f, "-t", f"{dur:.3f}", "-an",
        "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-g", "15",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(o)])


def clean_timeline(tl):
    """Validate what the browser sent and recompute record positions."""
    clips, pos = [], 0.0
    for c in tl["clips"]:
        dur = round(float(c["dur"]), 3)
        if dur <= 0:
            continue
        src_in = max(0.0, float(c["src_in"]))
        c = dict(c, src_in=round(src_in, 3), dur=dur, rec_in=round(pos, 3), hero=bool(c.get("hero")))
        clips.append(c)
        pos += dur
    if not clips:
        raise ValueError("timeline is empty")
    return dict(tl, clips=clips)


def save(trip, tl):
    import autocut
    d = trip_dir(trip)
    tl = clean_timeline(tl)
    for c in tl["clips"]:
        check_file(d, c["file"])
    cur = d / "timeline.json"
    shutil.copyfile(cur, d / "timeline.prev.json")
    cur.write_text(json.dumps(tl, indent=1), encoding="utf-8")
    with AUTOCUT_LOCK:
        autocut.W, autocut.H = frame_size(tl)
        autocut.write_fcpxml(tl["clips"], tl["music"], d / "reel_timeline.fcpxml", name=tl.get("name", trip))
    return tl


def render_job(trip):
    try:
        import autocut
        d = trip_dir(trip)
        tl = load_json(d / "timeline.json")
        RENDER.update(state="running", msg="rendering full-quality preview...", trip=trip)
        with AUTOCUT_LOCK:
            autocut.OUTDIR = d                   # render_preview keeps its temp parts here
            autocut.W, autocut.H = frame_size(tl)
            autocut.render_preview(tl["clips"], tl["music"], tl.get("lut"), d / "reel_preview.mp4")
        RENDER.update(state="done", msg=f"saved {d / 'reel_preview.mp4'}")
    except Exception as e:
        traceback.print_exc()
        RENDER.update(state="error", msg=str(e))


def insta_info(trip):
    """What would be posted: account, file checks, and whether the render is older than the edit."""
    import insta_post as ig
    d = trip_dir(trip)
    vid = d / "reel_preview.mp4"
    info = dict(file=str(vid), ready=False, account=None, problems=[], warnings=[])
    if not vid.exists():
        info["problems"].append("No render yet - press Render preview first.")
    else:
        try:
            pf = ig.preflight(vid)
            info.update(dur=pf["dur"], size=pf["size"], w=pf["w"], h=pf["h"], warnings=pf["warnings"])
        except ig.PostError as e:
            info["problems"].append(str(e))
        if (d / "timeline.json").stat().st_mtime > vid.stat().st_mtime + 1:
            info["warnings"].append("The timeline was saved after this render - Render preview again to post your latest edit.")
    try:
        info["account"] = ig.account(ig.load_env()).get("username")
    except ig.PostError as e:
        info["problems"].append(str(e))
    info["ready"] = not info["problems"]
    return info


def post_job(trip, caption, feed):
    import insta_post as ig
    try:
        vid = trip_dir(trip) / "reel_preview.mp4"
        ig.preflight(vid)
        link = ig.publish(vid, caption, ig.load_env(), share_to_feed=feed,
                          log=lambda m: POST.update(msg=m))
        POST.update(state="done", msg="Posted to Instagram", link=link if str(link).startswith("http") else None)
    except Exception as e:
        POST.update(state="error", msg=str(e))


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):     # keep the console quiet except for errors
        if args and str(args[1])[:1] in "45":
            sys.stderr.write("  " + (fmt % args) + "\n")

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def send_file(self, p, ctype=None, cache=True):
        """Serve a file with HTTP Range support (needed for seeking in <video>/<audio>)."""
        size = p.stat().st_size
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else end
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype or mimetypes.guess_type(str(p))[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        try:
            with open(p, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass                                  # browser cancelled (normal while seeking)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self.send_file(UI, "text/html; charset=utf-8", cache=False)
            if u.path == "/api/trips":
                trips = sorted(p.parent.name for p in OUT.glob("*/timeline.json"))
                return self.send_json(dict(trips=trips, out=str(OUT)))
            if u.path == "/api/timeline":
                d = trip_dir(q["trip"])
                shots = [s for s in load_json(d / "shots.json", []) if not s.get("reject")]
                shots.sort(key=lambda s: -s.get("score", 0))
                return self.send_json(dict(timeline=load_json(d / "timeline.json"), shots=shots,
                                           has_prev=(d / "timeline.prev.json").exists(),
                                           has_preview=(d / "reel_preview.mp4").exists()))
            if u.path == "/api/status":
                return self.send_json(RENDER)
            if u.path == "/api/insta":
                return self.send_json(insta_info(q["trip"]))
            if u.path == "/api/poststatus":
                return self.send_json(POST)
            if u.path == "/thumb":
                d = trip_dir(q["trip"])
                size = frame_size(load_json(d / "timeline.json"))
                return self.send_file(thumb(d, check_file(d, q["file"]), q.get("t", 0), size), "image/jpeg")
            if u.path == "/proxy":
                d = trip_dir(q["trip"])
                tl = load_json(d / "timeline.json", {})
                return self.send_file(proxy(d, check_file(d, q["file"]), q["t"], q["dur"],
                                            q.get("hero") == "1", tl.get("lut"), frame_size(tl)), "video/mp4")
            if u.path == "/music":
                d = trip_dir(q["trip"])
                return self.send_file(Path(load_json(d / "timeline.json")["music"]))
            if u.path == "/preview":
                d = trip_dir(q["trip"])
                return self.send_file(d / "reel_preview.mp4", "video/mp4", cache=False)
            self.send_json(dict(error="not found"), 404)
        except PermissionError as e:
            self.send_json(dict(error=str(e)), 403)
        except (ValueError, KeyError, FileNotFoundError) as e:
            self.send_json(dict(error=str(e)), 400)
        except Exception as e:
            traceback.print_exc()
            self.send_json(dict(error=str(e)), 500)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            if u.path == "/api/save":
                tl = save(q["trip"], json.loads(body))
                return self.send_json(dict(ok=True, timeline=tl))
            if u.path == "/api/revert":
                d = trip_dir(q["trip"])
                prev = d / "timeline.prev.json"
                if not prev.exists():
                    raise ValueError("no previous version")
                return self.send_json(dict(ok=True, timeline=load_json(prev)))
            if u.path == "/api/post":
                if POST["state"] == "running":
                    raise ValueError("already posting")
                req = json.loads(body or b"{}")
                caption = str(req.get("caption", ""))
                if len(caption) > 2200:
                    raise ValueError("caption is over 2200 characters")
                if not insta_info(q["trip"])["ready"]:
                    raise ValueError("not ready to post - see the checks in the dialog")
                POST.update(state="running", msg="starting upload...", link=None)
                threading.Thread(target=post_job, args=(q["trip"], caption, bool(req.get("feed", True))),
                                 daemon=True).start()
                return self.send_json(dict(ok=True))
            if u.path == "/api/render":
                if RENDER["state"] == "running":
                    raise ValueError("a render is already running")
                trip_dir(q["trip"])
                RENDER.update(state="running", msg="starting render...", trip=q["trip"])
                threading.Thread(target=render_job, args=(q["trip"],), daemon=True).start()
                return self.send_json(dict(ok=True))
            self.send_json(dict(error="not found"), 404)
        except (ValueError, KeyError, PermissionError) as e:
            self.send_json(dict(error=str(e)), 400)
        except Exception as e:
            traceback.print_exc()
            self.send_json(dict(error=str(e)), 500)


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", default=str(OUT), help="output folder holding <trip>\\timeline.json")
    ap.add_argument("--open", action="store_true", help="open the editor in your web browser")
    a = ap.parse_args()
    OUT = Path(a.out).resolve()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found - " + INSTALL_HINT)
    trips = sorted(p.parent.name for p in OUT.glob("*/timeline.json"))
    print(f"ReelLab editor  ->  http://127.0.0.1:{a.port}")
    print(f"  timelines in {OUT}: {', '.join(trips) or 'none yet - run autocut.py first'}")
    print("  Ctrl+C to stop")
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    except OSError:
        sys.exit(f"port {a.port} is busy - is the editor already open? Or use --port 8766")
    if a.open:
        import webbrowser
        threading.Timer(0.5, webbrowser.open, (f"http://127.0.0.1:{a.port}",)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
