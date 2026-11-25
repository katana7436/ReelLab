r"""
insta_post.py - publish a finished reel to Instagram with the official Instagram Graph API.

  python insta_post.py --check                                   # test the token, show the account
  python insta_post.py output\kerala\reel_preview.mp4 --caption "Kerala backwaters"
  python insta_post.py output\kerala\reel_preview.mp4 --caption-file caption.txt --dry-run

Uploads the local file straight to Meta ("resumable upload", no public link needed),
waits until Instagram has processed it, then publishes it as a Reel. It asks before posting
unless you pass --yes.

Needs an Instagram Professional account (Creator or Business) linked to a Facebook Page, and a
Meta app using Facebook Login for Business. Put the values in .env in the ReelLab folder (see .env.example):
  IG_USER_ID=...           Instagram account ID (not your @name)
  IG_ACCESS_TOKEN=...      long-lived token with instagram_basic + instagram_content_publish
  IG_API_VERSION=v23.0     optional
Standard library only: nothing extra to install.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"
MAX_BYTES = 300 * 1024 * 1024          # Instagram Reels limits
MIN_S, MAX_S = 3, 15 * 60


class PostError(Exception):
    pass


# ---------- config ----------
def load_env(path=ROOT / ".env"):
    """Tiny .env reader (KEY=value per line, # comments). Real environment variables win."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    cfg = dict(user=os.environ.get("IG_USER_ID", ""), token=os.environ.get("IG_ACCESS_TOKEN", ""),
               ver=os.environ.get("IG_API_VERSION", "v23.0"))
    missing = [n for n, k in (("IG_USER_ID", "user"), ("IG_ACCESS_TOKEN", "token")) if not cfg[k]]
    if missing:
        raise PostError(f"missing {', '.join(missing)} in {path} - copy .env.example to .env and fill it in "
                        "(steps in README.md, section 'Post to Instagram')")
    return cfg


# ---------- HTTP ----------
def call(method, url, params=None, data=None, headers=None, timeout=60):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            err = json.loads(body).get("error", {})
            msg = err.get("error_user_msg") or err.get("message") or body
            code = err.get("code")
        except ValueError:
            msg, code = body[:300], None
        hint = {190: " (token expired or wrong - make a new long-lived token)",
                10: " (permission missing - token needs instagram_content_publish)",
                200: " (permission missing - token needs instagram_content_publish)",
                100: " (check IG_USER_ID is the Instagram account ID, not the Page ID)"}.get(code, "")
        raise PostError(f"Instagram API error {e.code}: {msg}{hint}") from None
    except urllib.error.URLError as e:
        raise PostError(f"network error: {e.reason}") from None


def graph(cfg, method, path, **params):
    params["access_token"] = cfg["token"]
    # send the token in the POST body / query string over HTTPS, never logged
    if method == "POST":
        return call("POST", f"{GRAPH}/{cfg['ver']}/{path}", data=urllib.parse.urlencode(params).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    return call("GET", f"{GRAPH}/{cfg['ver']}/{path}", params=params)


# ---------- checks ----------
def probe(video):
    """Duration / size / codecs via ffprobe, to catch what Instagram would reject."""
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration,format_name:stream=codec_type,codec_name,width,height",
                        "-of", "json", str(video)], capture_output=True, text=True)
    if r.returncode:
        raise PostError(f"can't read {video}: {r.stderr.strip()[:200]}")
    j = json.loads(r.stdout)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    return dict(dur=float(j.get("format", {}).get("duration", 0)), w=v.get("width"), h=v.get("height"),
                vcodec=v.get("codec_name"), acodec=a and a.get("codec_name"))


def preflight(video):
    p = Path(video)
    if not p.exists():
        raise PostError(f"not found: {p}")
    if p.suffix.lower() not in (".mp4", ".mov"):
        raise PostError("Instagram Reels need an .mp4 or .mov file")
    size = p.stat().st_size
    if size > MAX_BYTES:
        raise PostError(f"file is {size / 1e6:.0f} MB, Instagram's limit is 300 MB")
    info = probe(p)
    problems, warnings = [], []
    if not MIN_S <= info["dur"] <= MAX_S:
        problems.append(f"length {info['dur']:.1f}s (Reels must be 3s - 15min)")
    if info["vcodec"] not in ("h264", "hevc"):
        problems.append(f"video codec {info['vcodec']} (use H.264)")
    if info["acodec"] is None:
        warnings.append("no audio track - add music in the Instagram app afterwards if you want")
    elif info["acodec"] != "aac":
        warnings.append(f"audio codec {info['acodec']} (AAC is safest)")
    if info["w"] and info["h"] and info["w"] > info["h"]:
        warnings.append(f"{info['w']}x{info['h']} is landscape - Reels show best at 9:16 (1080x1920)")
    if problems:
        raise PostError("Instagram would reject this file: " + "; ".join(problems))
    return dict(info, size=size, warnings=warnings)


def account(cfg):
    return graph(cfg, "GET", cfg["user"], fields="username,name")


# ---------- publish ----------
def publish(video, caption, cfg, share_to_feed=True, log=print, wait_s=600):
    """Create container -> upload bytes -> wait for processing -> publish. Returns the permalink."""
    video = Path(video)
    size = video.stat().st_size
    log("1/4 creating upload slot...")
    c = graph(cfg, "POST", f"{cfg['user']}/media", media_type="REELS", upload_type="resumable",
              caption=caption, share_to_feed="true" if share_to_feed else "false")
    cid = c.get("id")
    if not cid:
        raise PostError(f"no container id in reply: {c}")

    log(f"2/4 uploading {size / 1e6:.1f} MB...")
    with open(video, "rb") as f:
        r = call("POST", f"{RUPLOAD}/{cfg['ver']}/{cid}", data=f.read(), timeout=900, headers={
            "Authorization": f"OAuth {cfg['token']}", "offset": "0", "file_size": str(size),
            "Content-Type": "application/octet-stream"})
    if not r.get("success", True):
        raise PostError(f"upload failed: {r}")

    log("3/4 waiting for Instagram to process the video...")
    t0 = time.time()
    while True:
        s = graph(cfg, "GET", cid, fields="status_code,status")
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise PostError(f"Instagram could not process the video: {s.get('status') or code}")
        if time.time() - t0 > wait_s:
            raise PostError(f"still processing after {wait_s // 60} min - container {cid} was not published")
        time.sleep(5)

    log("4/4 publishing...")
    m = graph(cfg, "POST", f"{cfg['user']}/media_publish", creation_id=cid)
    mid = m.get("id")
    if not mid:
        raise PostError(f"publish failed: {m}")
    try:
        link = graph(cfg, "GET", mid, fields="permalink").get("permalink")
    except PostError:
        link = None
    return link or f"published (media id {mid})"


def main():
    ap = argparse.ArgumentParser(description="Post a reel to Instagram")
    ap.add_argument("video", nargs="?")
    ap.add_argument("--caption", default="")
    ap.add_argument("--caption-file", help="read the caption from a UTF-8 text file (good for long captions / hashtags)")
    ap.add_argument("--no-feed", action="store_true", help="Reels tab only, don't also show it in the main feed")
    ap.add_argument("--check", action="store_true", help="only test the token and show which account it posts to")
    ap.add_argument("--dry-run", action="store_true", help="check the file and settings, post nothing")
    ap.add_argument("--yes", action="store_true", help="don't ask before posting")
    a = ap.parse_args()
    try:
        if a.check:
            cfg = load_env(); acc = account(cfg)
            print(f"OK - token works, posts go to @{acc.get('username')} ({acc.get('name', '')})")
            return
        if not a.video:
            ap.error("give the video to post, or --check")
        caption = Path(a.caption_file).read_text(encoding="utf-8").strip() if a.caption_file else a.caption
        if len(caption) > 2200:
            raise PostError(f"caption is {len(caption)} characters, Instagram allows 2200")
        info = preflight(a.video)
        print(f"{a.video}: {info['w']}x{info['h']}, {info['dur']:.1f}s, {info['size'] / 1e6:.1f} MB")
        for w in info["warnings"]:
            print("  note:", w)
        cfg = load_env(); acc = account(cfg)
        print(f"account: @{acc.get('username')}\ncaption: {caption or '(none)'}")
        if a.dry_run:
            print("dry run - nothing posted"); return
        if not a.yes and input("Post this publicly now? Type yes: ").strip().lower() != "yes":
            print("not posted"); return
        print("posted:", publish(a.video, caption, cfg, share_to_feed=not a.no_feed))
    except PostError as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
