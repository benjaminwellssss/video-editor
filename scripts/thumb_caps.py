"""Facecam screencaps for a thumbnail: the N moments in a video where the streamer laughs or gets loud.

Usage: python thumb_caps.py <cut.json> <source.mp4> <mic_track> <out_dir> [--words words.json] [--n 5]

<cut.json> is the video's cut list, in either format: build_vod_cut's [{start, end, rec}, ...] (seconds), or a
short's {"cut": [[timeline_start, timeline_end, source_start], ...]} (frames at 30 fps). Moments come from the
streamer's OWN mic track (friends and game never count), over the source ranges the video actually uses; a loud
stretch with no transcribed word near it (a laugh) scores higher than loud talking. Frames are taken from the
source recording at full resolution and cropped to the facecam box around the face. Needs OpenCV (cv2).
Files are named cap_<rank>_<mm-ss>.png, best first, with the time in the video's own timeline.
"""
import json
import os
import subprocess
import sys

import numpy as np

SR, HOP = 8000, 0.05
SMOOTH_S = 0.3
FLOOR_DB = -30.0          # the streamer's mic above this is talking/laughing; breathing sits far below
LAUGH_BONUS_DB = 6.0      # loud with no word within WORD_PAD_S
WORD_PAD_S = 0.25
CROP_W, CROP_H = 8.0, 4.5 # crop box in face widths (the 10-14 facecam box is ~7.5 x 4.2 face widths)
FACE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "models", "face_detection_yunet_2023mar.onnx")


def ranges(cut_path):
    """[(source_start_s, timeline_start_s, duration_s)]"""
    d = json.load(open(cut_path, encoding="utf8"))
    if isinstance(d, dict):
        return [(src / 30, a / 30, (b - a) / 30) for a, b, src in d["cut"]]
    return [(s["start"], s["rec"], s["end"] - s["start"]) for s in d]


def mic_db(mic, start, dur):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", mic,
                          "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float) / 32768
    hop = int(SR * HOP)
    n = len(x) // hop
    db = 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    k = max(1, int(SMOOTH_S / HOP))
    return np.convolve(db, np.ones(k) / k, "same")


def pick(cands, n, gap):
    """Highest-scoring moments, at least `gap` seconds apart on the video's timeline."""
    out = []
    for score, tl, src in sorted(cands, reverse=True):
        if all(abs(tl - o[1]) >= gap for o in out):
            out.append((score, tl, src))
        if len(out) == n:
            break
    return sorted(out, key=lambda c: c[1])


def moments(cut, mic, words, n):
    starts = np.array([w["start"] for w in words]) if words else np.array([])
    ends = np.array([w["end"] for w in words]) if words else np.array([])
    cands = []
    for src0, tl0, dur in cut:
        db = mic_db(mic, src0, dur)
        for i in range(1, len(db) - 1):
            if db[i] < FLOOR_DB or db[i] < db[i - 1] or db[i] < db[i + 1]:
                continue
            src = src0 + i * HOP
            talking = bool(len(starts)) and bool(((starts - WORD_PAD_S <= src) & (ends + WORD_PAD_S >= src)).any())
            cands.append((db[i] + (0 if talking else LAUGH_BONUS_DB), tl0 + i * HOP, src))
    total = sum(c[2] for c in cut)
    return pick(cands, n, max(3.0, total / (3 * n)))


def grab(source, t):
    import cv2
    png = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", source, "-frames:v", "1",
                          "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)


def face(frame):
    import cv2
    h, w = frame.shape[:2]
    det = cv2.FaceDetectorYN.create(FACE_MODEL, "", (w, h), 0.7)
    _, found = det.detect(frame)
    return None if found is None else [tuple(f[:4]) for f in found]


def crop_box(cx, cy, fw, w, h):
    bw, bh = min(w, CROP_W * fw), min(h, CROP_H * fw)
    x = int(min(max(cx - bw / 2, 0), w - bw))
    y = int(min(max(cy - bh / 2, 0), h - bh))
    return x, y, int(bw), int(bh)


def main():
    import cv2
    args = sys.argv[1:]
    cut_path, source, mic, out_dir = args[:4]
    n = int(args[args.index("--n") + 1]) if "--n" in args else 5
    words = []
    if "--words" in args:
        d = json.load(open(args[args.index("--words") + 1], encoding="utf8"))
        words = [w for s in d["segments"] for w in s.get("words", []) if "start" in w] if isinstance(d, dict) else d
    picks = moments(ranges(cut_path), mic, words, n)
    frames = [grab(source, src + 0.1) for _, _, src in picks]
    faces = [face(f) or [] for f in frames]
    allf = np.array([f for fs in faces for f in fs]) if any(faces) else None
    if allf is None:
        sys.exit("thumb_caps: no face found in any frame")
    mx, my = np.median(allf[:, 0] + allf[:, 2] / 2), np.median(allf[:, 1] + allf[:, 3] / 2)
    mw = float(np.median(allf[:, 2]))
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):  # a re-run replaces the old set
        if old.startswith("cap_") and old.endswith(".png"):
            os.remove(os.path.join(out_dir, old))
    # numbered by score: the loudest wordless burst (the open-mouth yell/laugh the user picks) is cap_1
    ranked = sorted(zip(picks, frames, faces), key=lambda r: -r[0][0])
    for k, ((score, tl, src), frame, fs) in enumerate(ranked, 1):
        # the face nearest the usual spot (a stray hit in the gameplay is ignored)
        near = [f for f in fs if abs(f[0] + f[2] / 2 - mx) < 2 * mw and abs(f[1] + f[3] / 2 - my) < 2 * mw]
        cx, cy, fw = (near[0][0] + near[0][2] / 2, near[0][1] + near[0][3] / 2, mw) if near else (mx, my, mw)
        x, y, bw, bh = crop_box(cx, cy, fw, frame.shape[1], frame.shape[0])
        name = f"cap_{k}_{int(tl // 60):02d}-{int(tl % 60):02d}.png"
        cv2.imwrite(os.path.join(out_dir, name), frame[y:y + bh, x:x + bw])
        print(f"  {name}: source {src:.1f}s, mic {score:.1f}", flush=True)


if __name__ == "__main__":
    assert [c[1] for c in pick([(5, 10, 0), (4, 11, 0), (3, 20, 0)], 2, 3)] == [10, 20]  # spacing beats score
    assert crop_box(1900, 1000, 60, 1920, 1080) == (1440, 810, 480, 270)                  # clamped inside frame
    main()
