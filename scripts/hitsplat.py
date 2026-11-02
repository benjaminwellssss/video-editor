"""Cover each swear with a blue "0" RuneScape hitsplat on the speaker's mouth (video only; censor_noise.py does the audio).

The face is found with YuNet in the facecam panel (top 612 px of a 1080x1920 short); the mouth is the midpoint of its two
mouth-corner landmarks. The splat pops in over a few frames and follows the mouth for the length of each hit.

Usage: python hitsplat.py <in.mp4> <out.mp4> <hits.json | cut.json> [--panel y:h]
    hits.json = [[start_s, end_s, word], ...]; a cut.json (shorts proof) gets its hits from censor_noise.short_hits.
composite_short.py calls this for every censored word spoken by the person on the facecam.
"""
from local_paths import streaming
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FACE_MODEL = os.path.join(HERE, "..", "assets", "models", "face_detection_yunet_2023mar.onnx")
SPLAT = streaming(r"Overlays + Images\Video Overlays\hitsplats\zero_damage_hitsplat.png")
PANEL_H = 612
SPLAT_PER_FACE = 0.58           # splat width as a share of the face width (4x = 96 px on the 165 px face of the cam_top layout)
MIN_S, MAX_S = 0.45, 0.7        # splat on-screen time per hit
POP = [0.55, 0.85, 1.15, 1.0]   # first frames: scale pop

# 5x7 "0" in the OSRS look: white with a black drop shadow
ZERO = ["01110", "10001", "10001", "10001", "10001", "10001", "01110"]


def splat_with_zero():
    """Blue zero-damage sprite with a pixel "0" on it, at native size (nearest-neighbour upscaling happens later)."""
    from PIL import Image
    im = Image.open(SPLAT).convert("RGBA")
    px = im.load()
    ox, oy = (im.width - 5) // 2, (im.height - 7) // 2
    for pass_color, (dx, dy) in (((0, 0, 0, 255), (1, 1)), ((255, 255, 255, 255), (0, 0))):
        for r, row in enumerate(ZERO):
            for c, ch in enumerate(row):
                if ch == "1":
                    px[ox + c + dx, oy + r + dy] = pass_color
    return np.array(im)  # RGBA


def mouth_track(frames_bgr_by_idx, det, y0=0):
    """frame index -> (x, y, face width) for frames where a face was found; y is in full-frame pixels (y0 = panel top)."""
    out = {}
    for i, f in frames_bgr_by_idx.items():
        det.setInputSize((f.shape[1], f.shape[0]))
        _, faces = det.detect(f)
        if faces is not None and len(faces):
            b = max(faces, key=lambda r: r[2] * r[3])
            out[i] = ((b[10] + b[12]) / 2, y0 + (b[11] + b[13]) / 2, b[2])  # right/left mouth corner landmarks
    return out


def paste(frame, sprite_rgba, cx, cy, scale):
    h, w = sprite_rgba.shape[:2]
    s = cv2.resize(sprite_rgba, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_NEAREST)
    sh, sw = s.shape[:2]
    x0, y0 = round(cx - sw / 2), round(cy - sh / 2)
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + sw, frame.shape[1]), min(y0 + sh, frame.shape[0])
    if xa >= xb or ya >= yb:
        return
    s = s[ya - y0:yb - y0, xa - x0:xb - x0]
    a = s[:, :, 3:4] / 255.0
    frame[ya:yb, xa:xb] = (frame[ya:yb, xa:xb] * (1 - a) + s[:, :, [2, 1, 0]] * a).astype(np.uint8)  # sprite is RGB, frame BGR


def apply(src, dst, hits, panel=(0, PANEL_H)):
    y0, ph = panel
    cap = cv2.VideoCapture(src)
    fps, w, h = cap.get(cv2.CAP_PROP_FPS), int(cap.get(3)), int(cap.get(4))
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sprite = splat_with_zero()
    wins = []
    for s, e, _ in hits:
        d = min(max(e - s, MIN_S), MAX_S)
        wins.append((round(s * fps), round((s + d) * fps)))
    det = cv2.FaceDetectorYN.create(FACE_MODEL, "", (w, ph), 0.7)
    # pass 1: mouth positions in every window frame (plus 20 frames either side so a missed detection can borrow a neighbour)
    need = {i for a, b in wins for i in range(a - 20, b + 20)}
    track, frames = {}, {}
    for i in range(n_total):
        ok, f = cap.read()
        if not ok:
            break
        if i in need:
            frames[i] = f[y0:y0 + ph].copy()
        if i > max(b for _, b in wins) + 20:
            break
    track = mouth_track(frames, det, y0)
    keys = sorted(track)
    cap.release()
    if not keys:
        print("WARNING: no face found near any hit, hitsplats skipped")
        shutil.copyfile(src, dst)
        return
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-",
           "-i", src, "-map", "0:v", "-map", "1:a", "-c:v", "h264_nvenc", "-preset", "p6", "-cq", "19", "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-movflags", "+faststart", dst]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(src)
    for i in range(n_total):
        if i % max(1, n_total // 20) == 0:
            print(f"frame {i}/{n_total}", flush=True)  # Cabtions' progress bar reads these
        ok, f = cap.read()
        if not ok:
            break
        for a, b in wins:
            if a <= i < b:
                near = min(keys, key=lambda k: abs(k - i))
                x, y, fw = track[near]
                sc = max(2, round(SPLAT_PER_FACE * fw / sprite.shape[1]))  # whole-number scale keeps the pixels square
                paste(f, sprite, x, y, sc * POP[min(i - a, len(POP) - 1)])
        enc.stdin.write(f.tobytes())
    enc.stdin.close()
    assert enc.wait() == 0, "ffmpeg encode failed"
    cap.release()
    print(f"{len(wins)} hitsplats -> {dst}; mouth found on {len(track)} frames")


if __name__ == "__main__":
    import json
    a = sys.argv[1:]
    panel = tuple(int(v) for v in a[a.index("--panel") + 1].split(":")) if "--panel" in a else (0, PANEL_H)
    if a[2].endswith("_cut.json"):
        import censor_noise
        hits = censor_noise.short_hits(a[2])
    else:
        hits = json.load(open(a[2], encoding="utf-8"))
    apply(a[0], a[1], hits, panel)
