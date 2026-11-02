"""Finish a short in one step: dynamic zoom, captions, voice overlay, handle pop-up, trims.

Usage: python composite_short.py <clip_dir> [--words] [--no-zoom] [--punches 3.2,10.5]

<clip_dir> holds <clip>.mp4 (the 9:16 render), captions.json and, optionally, captions_speakers.json (the
caption editor's sidecar). Writes <clip_dir>/<clip>_captioned.mp4, replacing any older one. Steps:

1. auto_zoom.py: facecam zooms only while the streamer's own mic is active, following the face, no drift. The mic comes
   from the stream's job folder via <clip>_cut.json; with no cut or mic there's no auto zoom (--no-zoom skips; --punches adds moments)
2. fetches any image/GIF links in the caption notes that aren't cached yet
3. render_captions.py: phrase captions (two lines, spoken word lit) - --words keeps one word per card
4. render_captions.py --voices-only: the "who's talking" layer, unless the sidecar says "voice_overlay": false
5. the handle pop-up GIF, in a slot near 70% of the way through that no caption image overlaps
6. composites it all in that order over the zoomed clip, keeping the clip's audio
7. apply_trims.py, when the sidecar has "trims"
"""
from local_paths import streaming
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_captions as rc  # noqa: E402
import censor_noise  # noqa: E402
import short_layout  # noqa: E402
from media_info import video_fps  # noqa: E402
from caption_fx import fx_from_note  # noqa: E402

VENV_PY = os.path.join(os.path.expanduser("~"), ".cache", "video-editor", "whisperx-venv", "Scripts", "python.exe")
HANDLE_GIF = streaming(r"Overlays + Images\Video Overlays\bold\handle-pop.gif")  # see the handle pop-up memory
POPUP_W, POPUP_S = 396, 4.96  # centre comes from the layout (short_layout.py)
JOBS_DIR = streaming(r"video-editor-projects")
MIC_SR = 16000


def cut_mic(clip_dir, out):
    """Write the streamer's mic (OBS track 2), cut to the clip's timeline, to the wav <out>. <clip_dir> is
    Videos\\<MM-DD-YYYY> - <Game>\\Clips\\<clip>; its cut list and mic live in the stream's job folder. False if either is missing."""
    name = os.path.basename(clip_dir)
    date = os.path.basename(os.path.dirname(os.path.dirname(clip_dir))).split(" - ")[0]
    job = os.path.join(JOBS_DIR, f"stream-{date}-vod")
    cut_path = os.path.join(job, "shorts", name + "_cut.json")
    if not os.path.exists(cut_path):
        return False
    cut = json.load(open(cut_path, encoding="utf-8"))
    fps, rows = cut.get("fps", 30), cut["cut"]
    pcm = bytearray(int(max(r[1] for r in rows) / fps * MIC_SR) * 2)
    for row in rows:
        rec, rec_end, src = row[:3]
        mics = glob.glob(os.path.join(job, "raw", f"part{row[3]}_track2.m4a" if len(row) > 3 else "*_track2.m4a"))
        if len(mics) != 1:
            return False
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{src / fps:.3f}", "-t", f"{(rec_end - rec) / fps:.3f}", "-i", mics[0],
                              "-ac", "1", "-ar", str(MIC_SR), "-f", "s16le", "-"], capture_output=True, check=True).stdout
        at = int(rec / fps * MIC_SR) * 2
        raw = raw[:len(pcm) - at]
        pcm[at:at + len(raw)] = raw
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(MIC_SR)
        w.writeframes(bytes(pcm))
    return True


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


STEPS = 7


WINDOW_RE = re.compile(r"\bblur\w*\b.*?\b(?:window|box|panel)\b.*?[\"“]([^\"”]+)[\"”]", re.I)
WINDOW_S, TITLE_SIZE, TITLE_FADE = 2.5, 200, 0.4  # shortest time up, word size, blur fade-out


def title_windows(cards):
    """'add a blurred window at the beginning ... that says "X"' notes -> [(text, start, end)]: the whole frame blurs
    and X appears one word at a time, like the "headphone warning" card (user, 2026-10-30). Up for the card's own
    span, or WINDOW_S when the card is shorter."""
    return [(m.group(1), c["start"], max(c["end"], c["start"] + WINDOW_S))
            for c in cards for m in [WINDOW_RE.search(c.get("note") or "")] if m]


def title_words(text, a, b, voice=None):
    """[(word, start, end)]: each word on the voice's timing when there is a voice (intro_voice.json), otherwise
    evenly spaced over the title (a small head start, a short hold on the last word)."""
    words = text.upper().split()
    if voice and len(voice["words"]) == len(words):
        t0 = a + VOICE_T0
        out, carry = [], None
        for i, (w, (_, s, e)) in enumerate(zip(words, voice["words"])):
            if e - s < 0.16 and i + 1 < len(words):  # too short to read alone ("a"): show it with the next word
                carry = (f"{carry[0]} {w}" if carry else w, carry[1] if carry else s)
                continue
            w, s = (f"{carry[0]} {w}", carry[1]) if carry else (w, s)
            carry = None
            out.append((w, t0 + s, t0 + e if i + 1 < len(words) else b - 0.1))
        return out
    step = (b - a - 0.12 - 0.5) / len(words)
    return [(w, a + 0.12 + i * step, (a + 0.12 + (i + 1) * step) if i + 1 < len(words) else b - 0.1)
            for i, w in enumerate(words)]


VOICE_T0 = 0.12  # the voice starts this long after the title does


def load_voice(clip_dir):
    """intro_voice.json next to the clip: {"wav": "intro_voice.wav", "words": [[word, start_s, end_s], ...]} (times inside the wav)."""
    p = os.path.join(clip_dir, "intro_voice.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    return {"wav": os.path.join(clip_dir, d["wav"]), "words": d["words"]}


def word_png(word, font_file, tmp, k, i):
    """A full-frame transparent layer with one title word, white with a black outline, centred."""
    from PIL import Image, ImageDraw, ImageFont
    size = TITLE_SIZE
    f = ImageFont.truetype(font_file, size)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    while d.textlength(word, font=f) > 960:  # long words shrink to fit
        size -= 10
        f = ImageFont.truetype(font_file, size)
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((540, 960), word, font=f, fill=(255, 255, 255, 255), anchor="mm",
                             stroke_width=max(8, size // 14), stroke_fill=(0, 0, 0, 255))
    path = os.path.join(tmp, f"title{k}_{i}.png")
    img.save(path)
    return path


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
    fps = video_fps(clip)
    cards = json.load(open(captions, encoding="utf-8"))
    if not isinstance(cards, list) or not all(isinstance(c, dict) for c in cards):
        sys.exit(f"{captions} isn't a list of caption cards (it may have been overwritten by the speakers file).")
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    lay = short_layout.layout(sidecar)
    popup_cx, popup_cy = lay["popup"]

    with tempfile.TemporaryDirectory(prefix="composite_", ignore_cleanup_errors=True) as tmp:
        base = clip
        step(1, "zoom")
        if "--no-zoom" not in args:
            mic = os.path.join(tmp, "mic.wav")
            has_mic = cut_mic(clip_dir, mic)
            if has_mic or "--punches" in args:
                base = os.path.join(tmp, "zoom.mp4")
                if not has_mic:  # hand-placed punches only: a silent mic means no automatic zooms
                    with wave.open(mic, "wb") as w:
                        w.setnchannels(1), w.setsampwidth(2), w.setframerate(MIC_SR), w.writeframes(bytes(MIC_SR * 2))
                zoom = [zoom_python(), os.path.join(HERE, "auto_zoom.py"), clip, base, "--panel", "%d:%d" % lay["panel"], "--voice", mic, "--no-drift"]
                if "--punches" in args:
                    zoom += ["--punches", args[args.index("--punches") + 1]]
                run(zoom)
            if not has_mic:
                print("  zoom: no cut list or mic track found for this clip, so no automatic zoom", flush=True)

        step(2, "censor")
        # censored words (starred / emoji cards): grunt over every one, blue "0" hitsplat on the facecam person's mouth
        # for theirs only. "censor": false in the sidecar skips it (clips that already carry the grunt).
        if "--no-censor" not in args and sidecar.get("censor") is not False:
            audio_hits, splat_hits = censor_noise.hits_from_cards(cards, sidecar.get("facecam_speaker") or "Ben")
            if audio_hits:
                print(f"  censor: grunt on {len(audio_hits)} word(s), hitsplat on {len(splat_hits)}", flush=True)
                covered = os.path.join(tmp, "censored.mp4")
                censor_noise.apply(base, covered, audio_hits)
                base = covered
                if splat_hits:
                    hits_json, splatted = os.path.join(tmp, "splat_hits.json"), os.path.join(tmp, "splat.mp4")
                    json.dump(splat_hits, open(hits_json, "w"))
                    run([zoom_python(), os.path.join(HERE, "hitsplat.py"), base, splatted, hits_json, "--panel", "%d:%d" % lay["panel"]])
                    base = splatted

        step(3, "images")
        fetch_note_images(cards, clip_dir)
        step(4, "captions")
        caps = os.path.join(tmp, "caps.mov")
        run([py, os.path.join(HERE, "render_captions.py"), captions, f"{dur:.3f}", caps, "--fps", str(fps)] + ([] if "--words" in args else ["--phrases"]))

        step(5, "voice layer")
        if sidecar.get("voice_overlay") is not False and any(c.get("speaker") for c in cards):
            voices = os.path.join(tmp, "voices.mov")
            run([py, os.path.join(HERE, "render_captions.py"), captions, f"{dur:.3f}", voices, "--voices-only", "--fps", str(fps)])
        else:
            voices = None

        step(6, "composite")
        t0 = popup_start(dur, image_spans(captions, dur))
        print(f"  handle pop-up at {t0:.1f}s", flush=True)
        inputs = ["-i", base, "-i", caps, "-itsoffset", f"{t0:.2f}", "-i", HANDLE_GIF]
        graph = (f"[2:v]scale={POPUP_W}:-1[g];[0:v][1:v]overlay=0:0[a];"
                 f"[a][g]overlay=x={popup_cx}-w/2:y={popup_cy}-h/2:eof_action=pass[b]")
        if voices:
            inputs += ["-i", voices]
            graph += ";[b][3:v]overlay=0:0[w0]"
        else:
            graph += ";[b]null[w0]"
        wins = title_windows(cards)
        voice = load_voice(clip_dir)
        for k, (text, a, b) in enumerate(wins):  # full-frame blur + one-word-at-a-time title, on top of everything
            font_file = sidecar.get("font_file") or r"C:\Windows\Fonts\beachday.otf"
            graph += (f";[w{k}]split[w{k}a][w{k}b];[w{k}b]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS+{a:.3f}/TB,"
                      f"gblur=sigma=40,eq=brightness=-0.10,format=yuva420p,"
                      f"fade=t=out:st={b - TITLE_FADE:.3f}:d={TITLE_FADE}:alpha=1[bl{k}];"
                      f"[w{k}a][bl{k}]overlay=0:0:eof_action=pass[wc{k}_0]")
            tw = title_words(text, a, b, voice)
            for i, (word, ws, we) in enumerate(tw):
                n = inputs.count("-i")  # index of this word's layer
                inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", word_png(word, font_file, tmp, k, i)]
                last = i == len(tw) - 1
                graph += f";[wc{k}_{i}][{n}:v]overlay=0:0:enable='between(t,{ws:.3f},{we:.3f})'[" + (f"w{k + 1}" if last else f"wc{k}_{i + 1}") + "]"
            print(f"  title {a:.1f}-{b:.1f}s, one word at a time{' on the voice' if voice else ''}: {text!r}", flush=True)
        graph += f";[w{len(wins)}]null[v]"
        amap, acodec = ["-map", "0:a:0"], ["-c:a", "copy"]
        if voice and wins:  # the intro voice, mixed in over the clip's own audio
            n = inputs.count("-i")
            inputs += ["-i", voice["wav"]]
            ms = int((wins[0][1] + VOICE_T0) * 1000)
            graph += (f";[{n}:a]aresample=48000,pan=stereo|c0=c0|c1=c0,adelay={ms}|{ms},volume=1.5[vo];"
                      "[0:a][vo]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95:level=disabled[am]")
            amap, acodec = ["-map", "[am]"], ["-c:a", "aac", "-b:a", "192k"]
        composed = os.path.join(tmp, "composed.mp4")
        run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", *amap,
             "-c:v", "h264_nvenc", "-preset", "p6", "-cq", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
             *acodec, "-movflags", "+faststart", composed])

        step(7, "trims")
        if sidecar.get("trims"):
            run([sys.executable, os.path.join(HERE, "apply_trims.py"), composed, sidecar_path, out + ".tmp.mp4"])
        else:
            shutil.move(composed, out + ".tmp.mp4")  # temp dir is on C:, clips on E:
        os.replace(out + ".tmp.mp4", out)

    frames = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                             "stream=nb_read_frames", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    print(f"wrote {out}: {duration(out):.2f}s, {frames} frames")


if __name__ == "__main__":
    assert direct_url("https://giphy.com/gifs/loki-falling-AbC123") == "https://i.giphy.com/AbC123.gif"
    assert direct_url("https://media.giphy.com/media/AbC123/giphy.gif").endswith("giphy.gif")
    assert popup_start(60, [(40, 44)]) not in [x / 10 for x in range(351, 440)]  # never overlaps an image
    main()
