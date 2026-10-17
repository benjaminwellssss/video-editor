"""Dynamic camera for a finished 9:16 short: zooms in on the facecam when people laugh, following the face.

Usage: python auto_zoom.py <clip.mp4> <out.mp4> [--captions captions.json] [--punches 3.2,10.5] [--no-drift] [--dry]

Run it on the clip BEFORE the captions, voice overlay and handle pop-up go on. Needs OpenCV (cv2). No AI: it
reads the clip's own audio and caption timings; the face is found with OpenCV's small YuNet model
(assets/models/face_detection_yunet_2023mar.onnx, from github.com/opencv/opencv_zoo, Apache-2.0).

- Only the facecam panel (the top PANEL_H rows) zooms, and only inward: the panel never grows over the
  gameplay. The zoom is centred on the face (smoothed), kept inside the panel.
- Laughs get the big zoom. A laugh in the audio is loud, bursty voice (several bursts a few tenths of a second
  apart) where the captions have no words; loud talking is covered by words, so it doesn't count. It is then
  checked against the face: laughing moves the head (2-4% of face width per 0.1 s on the 10-14 clips, against
  about 1% or less when talking or still). Head moving: the big zoom, harder for longer, louder laughs. Some
  movement and a very strong audio laugh: a medium zoom. Still face (a pause, game noise, a friend's laugh):
  none. The zoom snaps in, holds while the laugh lasts (up to HOLD_MAX_S), then eases out.
- Other loud moments (a yell or slam well above the last few seconds, outside any laugh) get only a small
  bump, and only the biggest of them.
- --punches adds laugh-sized zooms by hand (seconds). --no-drift turns off the slow push in and out.
- --dry prints what it found without rendering.
"""
import json
import os
import subprocess
import sys

import numpy as np

W, H, FPS = 1080, 1920, 30
PANEL_H = 612                # facecam panel height in the 9:16 layout (the seam measures 612-616 on every 10-14 clip)
SR = 16000
HOP_S = 0.02
WORD_PAD_S = 0.12            # sound this close to a transcribed word counts as talking

LAUGH_FLOOR_DB = 16.0        # laugh audio must be within this many dB of the clip's loud moments (98th pct)
LAUGH_MIN_S = 0.45
LAUGH_MIN_BURSTS = 3         # "ha"s: envelope peaks...
BURST_DB = 3.0               # ...this far above the dips beside them...
BURST_GAP = (0.09, 0.45)     # ...this far apart
LAUGH_ZOOM = (0.22, 0.38)    # zoom added for a small..big confirmed laugh
LIKELY_ZOOM = 0.14           # audio laugh with only some head movement
MOTION_LAUGH, MOTION_LIKELY, LIKELY_AUDIO = 2.0, 1.0, 0.85   # head motion (% face width per 0.1 s), audio strength
LAUGH_MERGE_S = 1.0          # laughs closer than this become one long zoom
LAUGH_IN_S, LAUGH_OUT_S, HOLD_MAX_S = 0.15, 0.7, 4.0

SPIKE_CONTEXT_S, SPIKE_JUMP_DB = 3.0, 14.0
SPIKE_ZOOM = (0.05, 0.09)
SPIKE_IN_S, SPIKE_OUT_S = 0.08, 0.6
SPIKES_PER_S = 1 / 15        # at most one bump per 15 s of clip
MIN_GAP_S = 2.5

DRIFT_AMP, DRIFT_PERIOD_S = 0.04, 10.0
FACE_EVERY_S, FACE_SMOOTH_S = 0.1, 1.2
FACE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "models", "face_detection_yunet_2023mar.onnx")


def loudness(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    hop = int(SR * HOP_S)
    n = len(x) // hop
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9
    return 20 * np.log10(rms / 32768)


def word_mask(n, captions):
    """True for hops inside (or right next to) a transcribed word."""
    mask = np.zeros(n, bool)
    for c in captions:
        if " ".join(c.get("lines", [])).strip():
            a = max(0, int((c["start"] - WORD_PAD_S) / HOP_S))
            mask[a:int((c["end"] + WORD_PAD_S) / HOP_S) + 1] = True
    return mask


def count_bursts(db):
    """Envelope peaks at least BURST_DB above the dips on both sides, BURST_GAP apart."""
    lo, hi = int(BURST_GAP[0] / HOP_S), int(BURST_GAP[1] / HOP_S)
    peaks = [i for i in range(1, len(db) - 1) if db[i] >= db[i - 1] and db[i] > db[i + 1]
             and db[i] - db[max(0, i - hi):i].min(initial=db[i]) >= BURST_DB
             and db[i] - db[i + 1:i + hi + 1].min(initial=db[i]) >= BURST_DB]
    kept = []
    for p in peaks:
        if not kept or p - kept[-1] >= lo:
            kept.append(p)
    return sum(1 for a, b in zip(kept, kept[1:]) if b - a <= hi) + (1 if kept else 0)


def find_laughs(db, words):
    """[(start_s, end_s, strength 0..1)] for loud, bursty, wordless stretches."""
    loud = (db >= np.percentile(db, 98) - LAUGH_FLOOR_DB) & ~words
    # close small dips inside a laugh (the gaps between "ha"s)
    gap = int(BURST_GAP[1] / HOP_S)
    idx = np.flatnonzero(loud)
    regions = []
    for i in idx:
        if regions and i - regions[-1][1] <= gap and not words[regions[-1][1]:i].any():
            regions[-1][1] = i
        else:
            regions.append([i, i])
    top = np.percentile(db, 98)
    out = []
    for a, b in regions:
        dur = (b - a + 1) * HOP_S
        if dur < LAUGH_MIN_S:
            continue
        bursts = count_bursts(db[a:b + 1])
        if bursts < LAUGH_MIN_BURSTS:
            continue
        level = np.clip(1 - (top - np.percentile(db[a:b + 1], 90)) / LAUGH_FLOOR_DB, 0, 1)
        strength = float(np.clip(0.5 * min(dur / 2.0, 1) + 0.3 * level + 0.2 * min(bursts / 8, 1), 0, 1))
        if out and a * HOP_S - out[-1][1] < LAUGH_MERGE_S:
            out[-1] = (out[-1][0], (b + 1) * HOP_S, max(out[-1][2], strength))
        else:
            out.append((a * HOP_S, (b + 1) * HOP_S, strength))
    return out


def confirm_laughs(laughs, faces):
    """Audio laughs the face backs up: [(start, end, zoom amount, head motion)]. faces: {time_s: (cx, cy, w)}."""
    times = np.array(sorted(faces))
    out = []
    for a, b, s in laughs:
        pts = [faces[t] for t in times[(times >= a) & (times <= b)]]
        moves = [np.hypot(q[0] - p[0], q[1] - p[1]) / p[2] * 100 for p, q in zip(pts, pts[1:])]
        motion = float(np.mean(moves)) if moves else 0.0
        if motion >= MOTION_LAUGH:
            out.append((a, b, LAUGH_ZOOM[0] + (LAUGH_ZOOM[1] - LAUGH_ZOOM[0]) * s, motion))
        elif motion >= MOTION_LIKELY and s >= LIKELY_AUDIO:
            out.append((a, b, LIKELY_ZOOM, motion))
    return out


def find_spikes(db, laughs):
    """[(time_s, strength)] for the biggest sudden jumps that aren't part of a laugh."""
    k = int(SPIKE_CONTEXT_S / HOP_S)
    pad = np.pad(db, (k, 0), mode="edge")
    context = np.array([np.median(pad[i:i + k]) for i in range(len(db))])
    jump = db - context
    top = np.percentile(db, 98)
    cands = sorted((i for i in range(1, len(db) - 1) if jump[i] >= SPIKE_JUMP_DB and db[i] >= top - 10
                    and db[i] >= db[i - 1] and db[i] >= db[i + 1]), key=lambda i: -jump[i])
    chosen = []
    for i in cands:
        t = i * HOP_S
        if all(abs(t - c[0]) >= MIN_GAP_S * 2 for c in chosen) and all(not (a - MIN_GAP_S <= t <= b + MIN_GAP_S) for a, b, _ in laughs):
            chosen.append((t, float(np.clip((jump[i] - SPIKE_JUMP_DB) / 12, 0, 1))))
    return sorted(chosen[:int(len(db) * HOP_S * SPIKES_PER_S)])


def zoom_curve(n_frames, laughs, spikes, drift):
    """Zoom factor per video frame (1.0 = the panel as it is)."""
    t = np.arange(n_frames) / FPS
    z = np.zeros(n_frames)
    for a, b, amt in laughs:
        hold_end = a + LAUGH_IN_S + min(b - a, HOLD_MAX_S)
        up = np.clip((t - a) / LAUGH_IN_S, 0, 1)
        down = np.clip(1 - (t - hold_end) / LAUGH_OUT_S, 0, 1)
        shape = np.where(t < hold_end, 1 - (1 - up) ** 3, down ** 2) * (t >= a)  # snap in, ease out
        z = np.maximum(z, amt * shape)
    for t0, s in spikes:
        amt = SPIKE_ZOOM[0] + (SPIKE_ZOOM[1] - SPIKE_ZOOM[0]) * s
        up = np.clip((t - t0) / SPIKE_IN_S, 0, 1)
        down = np.clip(1 - (t - t0 - SPIKE_IN_S) / SPIKE_OUT_S, 0, 1)
        z = np.maximum(z, amt * np.where(t < t0 + SPIKE_IN_S, up, down ** 2) * (t >= t0))
    if drift:
        z += DRIFT_AMP * (1 - np.cos(2 * np.pi * t / DRIFT_PERIOD_S)) / 2
    return 1 + z


def find_faces(path, n_frames):
    """{time_s: (cx, cy, face_width)} for the biggest face in the panel, every FACE_EVERY_S."""
    import cv2
    if not os.path.exists(FACE_MODEL):
        sys.exit(f"auto_zoom: face model missing: {FACE_MODEL}")
    det = cv2.FaceDetectorYN.create(FACE_MODEL, "", (W // 2, PANEL_H // 2), 0.7)
    step = max(1, int(round(FACE_EVERY_S * FPS)))
    cap = cv2.VideoCapture(path)
    faces = {}
    for fi in range(n_frames):
        if not cap.grab():
            break
        if fi % step:
            continue
        _, frame = cap.retrieve()
        _, found = det.detect(cv2.resize(frame[:PANEL_H], (W // 2, PANEL_H // 2)))
        if found is not None:
            x, y, w, h = max(found, key=lambda f: f[2] * f[3])[:4] * 2
            faces[fi / FPS] = (float(x + w / 2), float(y + h / 2), float(w))
    cap.release()
    return faces


def face_track(faces, n_frames):
    """Smoothed (x, y) face centre per video frame; the panel centre if no face was ever found."""
    if not faces:
        return np.tile([W / 2, PANEL_H / 2], (n_frames, 1))
    keys = np.array(sorted(faces))
    pts = np.array([faces[k][:2] for k in keys])
    t = np.arange(n_frames) / FPS
    track = np.stack([np.interp(t, keys, pts[:, 0]), np.interp(t, keys, pts[:, 1])], 1)
    k = max(1, int(FACE_SMOOTH_S * FPS))
    kernel = np.ones(k) / k
    return np.stack([np.convolve(np.pad(track[:, i], (k // 2, k - k // 2 - 1), mode="edge"), kernel, "valid")
                     for i in range(2)], 1)


def crop_box(z, cx, cy):
    """The panel region (x, y, w, h) that fills the panel at zoom z, centred on (cx, cy), never outside it."""
    w, h = W / z, PANEL_H / z
    x = min(max(cx - w / 2, 0), W - w)
    y = min(max(cy - h / 2, 0), PANEL_H - h)
    return x, y, w, h


def render(src, out, zooms, track):
    import cv2
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", src, "-map", "0:v", "-map", "1:a:0", "-c:v", "h264_nvenc",
                            "-preset", "p6", "-cq", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
                            "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    size = W * H * 3
    fi = 0
    while True:
        buf = dec.stdout.read(size)
        if len(buf) < size:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        z = zooms[min(fi, len(zooms) - 1)]
        if z > 1.002:
            x, y, w, h = crop_box(z, *track[min(fi, len(track) - 1)])
            # sub-pixel crop + resize in one affine warp, so slow zooms don't jitter by whole pixels
            m = np.array([[w / W, 0, x], [0, h / PANEL_H, y]], np.float64)
            frame[:PANEL_H] = cv2.warpAffine(frame[:PANEL_H], m, (W, PANEL_H),
                                             flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
        enc.stdin.write(frame.tobytes())
        fi += 1
    enc.stdin.close()
    if enc.wait() or dec.wait():
        sys.exit("auto_zoom: ffmpeg failed")


def main():
    args = sys.argv[1:]
    src, out = args[0], args[1]
    cap_path = args[args.index("--captions") + 1] if "--captions" in args else os.path.join(os.path.dirname(os.path.abspath(src)), "captions.json")
    captions = json.load(open(cap_path, encoding="utf-8")) if os.path.exists(cap_path) else []
    db = loudness(src)
    n = int(round(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                                      capture_output=True, text=True, check=True).stdout) * FPS))
    faces = find_faces(src, n)
    print(f"  face found in {len(faces) / max(1, n // round(FACE_EVERY_S * FPS)):.0%} of sampled frames", flush=True)
    heard = find_laughs(db, word_mask(len(db), captions))
    confirmed = confirm_laughs(heard, faces)
    for a, b, strength in heard:
        hit = next((c for c in confirmed if c[0] == a), None)
        print(f"  {a:5.1f}-{b:5.1f}s audio {strength:.0%} -> "
              + (f"zoom +{hit[2]:.0%} (head motion {hit[3]:.1f})" if hit else "no zoom (face still)"), flush=True)
    laughs = [c[:3] for c in confirmed]
    if "--punches" in args:
        laughs = sorted(laughs + [(float(v), float(v) + 1.0, LAUGH_ZOOM[1] * 0.8)
                                  for v in args[args.index("--punches") + 1].split(",") if v.strip()])
    spikes = find_spikes(db, laughs)
    print(f"{len(laughs)} laugh zooms, {len(spikes)} small bumps: " + ", ".join(f"{t:.1f}s" for t, _ in spikes), flush=True)
    if not captions:
        print("  (no captions.json found: talking can't be told from laughing, so laugh detection is rough)", flush=True)
    if "--dry" in args:
        return
    render(src, out, zoom_curve(n, laughs, spikes, "--no-drift" not in args), face_track(faces, n))


if __name__ == "__main__":
    # self-check: wordless "ha-ha-ha" bursts are a laugh; the same loudness under words is not
    db = np.full(500, -45.0)
    for k in range(6):
        db[200 + k * 12:206 + k * 12] = -20.0
    words = np.zeros(500, bool)
    assert len(find_laughs(db, words)) == 1, find_laughs(db, words)
    words[190:280] = True
    assert find_laughs(db, words) == []
    still = {t / 10: (500.0, 300.0, 150.0) for t in range(100)}
    moving = {t / 10: (500.0 + (t % 2) * 6, 300.0, 150.0) for t in range(100)}
    assert confirm_laughs([(2.0, 4.0, 0.5)], still) == [] and len(confirm_laughs([(2.0, 4.0, 0.5)], moving)) == 1
    assert crop_box(1.25, 0, 0)[:2] == (0, 0) and crop_box(1.25, W, PANEL_H)[0] == W - W / 1.25  # stays in the panel
    main()
