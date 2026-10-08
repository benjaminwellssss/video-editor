"""Put a 2-5 second teaser (the short's funniest beat) in front of a finished short, so
viewers get hooked before the setup.

Usage:
    python add_teaser.py <clip_dir> --suggest
    python add_teaser.py <clip_dir> <start_s> <end_s> [--force]

<clip_dir> is a short's folder (<name>/<name>.mp4 + captions.json, optional captions.srt),
or a variant subfolder of one. --suggest prints the loudest 2-5 s word-aligned windows
(laughs and yelling are usually the payoff) to help pick; the moment itself is a judgment
call made from the transcript.

With a window, the teaser is cut from the short itself, snapped outward to word edges
(never starting or ending mid-word), and joined in front of the full clip with a 30 ms
audio fade on each edge so the joins don't click. captions.json gets the teaser
window's cards copied to the front (notes and all) and every original card shifted back
by the teaser length; captions.srt is rewritten from it, one cue per card. The pre-teaser
files move to <clip_dir>/no-teaser/ (a variant subfolder, per the deliverables rule);
refuses to run twice on the same folder unless --force.

Best run once the cut is final and before captions are hand-edited, so the teaser's
captions get edited with the rest; it works on edited captions too (it only shifts them).
"""
import json
import os
import shutil
import subprocess
import sys

import numpy as np

FADE = 0.03
TAIL = 0.15     # air left after the teaser's last word
MIN_LEN, MAX_LEN = 2.0, 5.0


def clip_paths(clip_dir):
    name = os.path.basename(os.path.normpath(clip_dir))
    mp4 = os.path.join(clip_dir, name + ".mp4")
    if not os.path.exists(mp4):
        cands = [f for f in os.listdir(clip_dir) if f.endswith(".mp4") and not f.endswith("_captioned.mp4")]
        if len(cands) != 1:
            raise SystemExit(f"can't tell which mp4 is the short in {clip_dir}: {cands}")
        mp4 = os.path.join(clip_dir, cands[0])
    return mp4, os.path.join(clip_dir, "captions.json"), os.path.join(clip_dir, "captions.srt")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def audio_rms(path, hop=0.05):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = int(16000 * hop)
    return np.sqrt(np.mean(x[: len(x) // n * n].reshape(-1, n) ** 2, axis=1)), hop


def text(card):
    return " ".join(card.get("lines", []))


def suggest(clip_dir):
    mp4, cards_path, _ = clip_paths(clip_dir)
    cards = json.load(open(cards_path, encoding="utf-8"))
    rms, hop = audio_rms(mp4)
    starts = [c["start"] for c in cards]
    found = []
    for i in range(len(cards)):
        for j in range(i, len(cards)):
            length = cards[j]["end"] - starts[i]
            if length > MAX_LEN:
                break
            if length < MIN_LEN:
                continue
            seg = rms[int(starts[i] / hop):int(cards[j]["end"] / hop) + 1]
            found.append((float(np.mean(seg)) + 0.5 * float(np.percentile(seg, 90)), starts[i], cards[j]["end"],
                          " ".join(text(c) for c in cards[i:j + 1])))
    found.sort(reverse=True)
    shown = []
    for score, a, b, words in found:
        if any(not (b <= sa or a >= sb) for sa, sb in shown):
            continue  # one suggestion per stretch of the clip
        shown.append((a, b))
        print(f"  {a:6.2f}-{b:6.2f}  ({b - a:.1f}s, loudness {score:.3f})  {words}")
        if len(shown) == 5:
            break


def snap(cards, start, end):
    """Widen [start, end] outward to card (word) edges without running into the next word."""
    first = min(cards, key=lambda c: abs(c["start"] - start))  # nearest word, so a rounded time can't grab its neighbor
    a = first["start"]
    inside = [c for c in cards if c["start"] < end]
    last = max(inside, key=lambda c: c["start"])
    later = [c for c in cards if c["start"] > last["start"]]
    b = last["end"] + TAIL
    if later:
        b = min(b, later[0]["start"] + 0.10)  # cards lead their word by ~0.12 s, so this stays before it
    return max(0.0, a), max(b, last["end"])


def tc(x):
    ms = round(x * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def add(clip_dir, start, end, force=False):
    mp4, cards_path, srt_path = clip_paths(clip_dir)
    keep = os.path.join(clip_dir, "no-teaser")
    if os.path.isdir(keep) and not force:
        raise SystemExit(f"{keep} already exists - this short already has a teaser (use --force to add another)")
    cards = json.load(open(cards_path, encoding="utf-8"))
    dur = duration(mp4)
    a, b = snap(cards, start, end)
    b = min(b, dur)
    tlen = b - a
    if not MIN_LEN - 0.5 <= tlen <= MAX_LEN + 0.5:
        print(f"  note: teaser is {tlen:.2f}s (aim for {MIN_LEN:.0f}-{MAX_LEN:.0f}s)")

    os.makedirs(keep, exist_ok=True)
    src = os.path.join(keep, os.path.basename(mp4))
    shutil.move(mp4, src)
    shutil.move(cards_path, os.path.join(keep, "captions.json"))
    if os.path.exists(srt_path):
        shutil.move(srt_path, os.path.join(keep, "captions.srt"))

    # the teaser and the full clip are read as two separate inputs: splitting one input would make
    # ffmpeg buffer every frame up to the teaser's position in memory
    graph = (f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[tv];"
             f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d={FADE},"
             f"afade=t=out:st={tlen - FADE:.3f}:d={FADE}[ta];"
             f"[1:a]afade=t=in:d={FADE}[ma];"
             f"[tv][ta][1:v][ma]concat=n=2:v=1:a=1[v][a]")
    subprocess.run(["ffmpeg", "-y", "-v", "warning", "-i", src, "-i", src, "-filter_complex", graph,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "h264_nvenc", "-preset", "p6", "-cq", "18", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", mp4], check=True)

    teaser = []
    for c in cards:
        if a - 1e-6 <= c["start"] < b:
            t = dict(c)
            t["start"] = round(c["start"] - a, 3)
            t["end"] = round(min(c["end"], b) - a, 3)
            if t["end"] > t["start"]:
                teaser.append(t)
    shifted = [dict(c, start=round(c["start"] + tlen, 3), end=round(c["end"] + tlen, 3)) for c in cards]
    out = teaser + shifted
    json.dump(out, open(cards_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with open(srt_path, "w", encoding="utf-8") as f:
        for n, c in enumerate(out, 1):
            f.write(f"{n}\n{tc(c['start'])} --> {tc(c['end'])}\n" + "\n".join(c.get("lines", [])) + "\n\n")

    new_dur = duration(mp4)
    frames = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                             "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", mp4],
                            capture_output=True, text=True).stdout.strip()
    print(f"  teaser {a:.2f}-{b:.2f}s ({tlen:.2f}s): {' '.join(text(c) for c in teaser)}")
    print(f"  {os.path.basename(mp4)}: {dur:.2f}s -> {new_dur:.2f}s ({frames} frames); "
          f"{len(teaser)} teaser cards + {len(shifted)} shifted; originals in no-teaser/")
    if abs(new_dur - (dur + tlen)) > 0.15:
        raise SystemExit(f"duration check failed: expected {dur + tlen:.2f}s")


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    if "--suggest" in sys.argv:
        suggest(args[0])
    elif len(args) == 3:
        add(args[0], float(args[1]), float(args[2]), force="--force" in sys.argv)
    else:
        raise SystemExit(__doc__)
