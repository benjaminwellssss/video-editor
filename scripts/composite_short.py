"""Finish a short in one step: dynamic zoom, captions, voice overlay, handle pop-up, trims.

Usage: python composite_short.py <clip_dir> [--words] [--no-zoom] [--punches 3.2,10.5]

<clip_dir> holds <clip>.mp4 (the 9:16 render), captions.json and, optionally, captions_speakers.json (the
caption editor's sidecar). Writes <clip_dir>/<clip>_captioned.mp4, replacing any older one. Steps:

1. auto_zoom.py: facecam zooms on laughs, following the face, plus a slow drift (--no-zoom skips; --punches adds moments)
2. fetches any image/GIF links in the caption notes that aren't cached yet
3. render_captions.py: phrase captions (two lines, spoken word lit) - --words keeps one word per card
4. render_captions.py --voices-only: the "who's talking" layer, unless the sidecar says "voice_overlay": false
5. the handle pop-up GIF, in a slot near 70% of the way through that no caption image overlaps
6. composites it all in that order over the zoomed clip, keeping the clip's audio
7. apply_trims.py, when the sidecar has "trims"
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_captions as rc  # noqa: E402
from caption_fx import fx_from_note  # noqa: E402

VENV_PY = os.path.join(os.path.expanduser("~"), ".cache", "video-editor", "whisperx-venv", "Scripts", "python.exe")
HANDLE_GIF = r"E:\Streaming\Overlays + Images\Video Overlays\bold\handle-pop.gif"  # see the handle pop-up memory
POPUP_W, POPUP_CX, POPUP_CY, POPUP_S = 396, 347, 1036, 4.96


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True, check=True).stdout)


def direct_url(url):
    """A GIPHY page link (giphy.com/gifs/name-ID) -> its GIF file; other links unchanged. The cache is still
    keyed on the link as written in the note, which is what render_captions looks up."""
    m = re.match(r"https?://(?:www\.)?giphy\.com/(?:gifs|stickers)/(?:[\w-]*-)?(\w+)/?$", url)
    return f"https://i.giphy.com/{m.group(1)}.gif" if m else url


def fetch_note_images(cards, clip_dir):
    cache = os.path.join(clip_dir, "note_images")
    os.makedirs(cache, exist_ok=True)
    for url in sorted({fx_from_note(c.get("note")).get("image_url") for c in cards if c.get("note")} - {None}):
        if not url.startswith("http"):
            continue
        h = hashlib.sha1(url.encode()).hexdigest()[:16]
        if any(os.path.exists(os.path.join(cache, h + e)) for e in (".gif", ".webp", ".png", ".jpg", ".jpeg")):
            continue
        try:
            for attempt in range(4):  # some hosts (Wikimedia) rate-limit with 429: wait and retry
                try:
                    data = urllib.request.urlopen(urllib.request.Request(direct_url(url), headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 3:
                        raise
                    time.sleep(5 * (attempt + 1))
            from PIL import Image
            fmt = Image.open(io.BytesIO(data)).format
            ext = {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp"}.get(fmt, "png")
            open(os.path.join(cache, f"{h}.{ext}"), "wb").write(data)
            print(f"  fetched {fmt} {url[:70]}", flush=True)
        except Exception as e:  # a dead link shouldn't stop the render; render_captions reports it as missing
            print(f"  could not fetch {url[:70]}: {e}", flush=True)
        time.sleep(0.4)


def image_spans(captions_path, dur):
    lanes = rc.split_lanes(json.load(open(captions_path, encoding="utf-8")))
    for i, cards in enumerate(lanes):
        rc.apply_fx_passes(cards, i)
    return [(o["start"], o["end"]) for o in rc.gather_image_overlays(lanes, captions_path, dur)]


def popup_start(dur, spans):
    """The free POPUP_S-long slot closest to 70% of the way through, clear of every caption image."""
    target = dur * 0.7
    slots = [t / 10 for t in range(0, int((dur - POPUP_S) * 10))]
    free = [t for t in slots if all(t + POPUP_S <= a or t >= b for a, b in spans)]
    return min(free, key=lambda t: abs(t - target)) if free else max(0.0, target)


STEPS = 6


def step(k, name):
    print(f"[step {k}/{STEPS}] {name}", flush=True)  # Cabtions' progress bar reads these


def zoom_python():
    """auto_zoom needs OpenCV, which the WhisperX venv (what Cabtions runs under) doesn't have."""
    import importlib.util
    import shutil
    if importlib.util.find_spec("cv2"):
        return sys.executable
    return shutil.which("python") or sys.exit("auto_zoom needs a Python with OpenCV (pip install opencv-python-headless)")


def run(cmd):
    subprocess.run(cmd, check=True)


def main():
    args = sys.argv[1:]
    clip_dir = os.path.abspath(args[0])
    name = os.path.basename(clip_dir)
    clip = os.path.join(clip_dir, name + ".mp4")
    captions = os.path.join(clip_dir, "captions.json")
    sidecar_path = os.path.join(clip_dir, "captions_speakers.json")
    sidecar = rc.load_sidecar(captions)
    out = os.path.join(clip_dir, name + "_captioned.mp4")
    dur = duration(clip)
    cards = json.load(open(captions, encoding="utf-8"))
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable

    with tempfile.TemporaryDirectory(prefix="composite_") as tmp:
        base = clip
        step(1, "zoom")
        if "--no-zoom" not in args:
            base = os.path.join(tmp, "zoom.mp4")
            zoom = [zoom_python(), os.path.join(HERE, "auto_zoom.py"), clip, base]
            if "--punches" in args:
                zoom += ["--punches", args[args.index("--punches") + 1]]
            run(zoom)

        step(2, "images")
        fetch_note_images(cards, clip_dir)
        step(3, "captions")
        caps = os.path.join(tmp, "caps.mov")
        run([py, os.path.join(HERE, "render_captions.py"), captions, f"{dur:.3f}", caps] + ([] if "--words" in args else ["--phrases"]))

        step(4, "voice layer")
        if sidecar.get("voice_overlay") is not False and any(c.get("speaker") for c in cards):
            voices = os.path.join(tmp, "voices.mov")
            run([py, os.path.join(HERE, "render_captions.py"), captions, f"{dur:.3f}", voices, "--voices-only"])
        else:
            voices = None

        step(5, "composite")
        t0 = popup_start(dur, image_spans(captions, dur))
        print(f"  handle pop-up at {t0:.1f}s", flush=True)
        inputs = ["-i", base, "-i", caps, "-itsoffset", f"{t0:.2f}", "-i", HANDLE_GIF]
        graph = (f"[2:v]scale={POPUP_W}:-1[g];[0:v][1:v]overlay=0:0[a];"
                 f"[a][g]overlay=x={POPUP_CX}-w/2:y={POPUP_CY}-h/2:eof_action=pass[b]")
        if voices:
            inputs += ["-i", voices]
            graph += ";[b][3:v]overlay=0:0[v]"
        else:
            graph += ";[b]null[v]"
        composed = os.path.join(tmp, "composed.mp4")
        run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0",
             "-c:v", "h264_nvenc", "-preset", "p6", "-cq", "18", "-pix_fmt", "yuv420p", "-r", "30",
             "-c:a", "copy", "-movflags", "+faststart", composed])

        step(6, "trims")
        if sidecar.get("trims"):
            run([sys.executable, os.path.join(HERE, "apply_trims.py"), composed, sidecar_path, out + ".tmp.mp4"])
        else:
            os.replace(composed, out + ".tmp.mp4")
        os.replace(out + ".tmp.mp4", out)

    frames = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                             "stream=nb_read_frames", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    print(f"wrote {out}: {duration(out):.2f}s, {frames} frames")


if __name__ == "__main__":
    assert direct_url("https://giphy.com/gifs/loki-falling-AbC123") == "https://i.giphy.com/AbC123.gif"
    assert direct_url("https://media.giphy.com/media/AbC123/giphy.gif").endswith("giphy.gif")
    assert popup_start(60, [(40, 44)]) not in [x / 10 for x in range(351, 440)]  # never overlaps an image
    main()
