"""Render a punch-in: crop rect animates from a wide starting box down to a
tight target box over the clip's duration, scaled to always fill the output
width, with a violent shake (caption fx_shake's own sin-sum formula) ramping
up from nothing to full amplitude by the end. Output has no audio; mux the
source segment's audio back on separately.

Usage: <python> build_shake_zoom_punch.py <src> <start> <end> <out.mp4>
  <full_box> <target_box> <canvas_w> <canvas_h>
full_box/target_box: "x,y,w,h" in source-frame pixels.
"""
import math
import subprocess
import sys

from PIL import Image


def lerp(a, b, u):
    return a + (b - a) * u


def ease(t):
    return t ** 2.5  # slow start, hard punch by the end


def main():
    src, start, end, out_path, full_box, target_box, cw, ch = sys.argv[1:9]
    start, end = float(start), float(end)
    fx, fy, fw, fh = (float(v) for v in full_box.split(","))
    tx, ty, tw, th = (float(v) for v in target_box.split(","))
    cw, ch = int(cw), int(ch)
    fps = 30
    n_frames = int(round((end - start) * fps))

    reader = subprocess.Popen([
        "ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", src,
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-r", str(fps), "-",
        "-loglevel", "error",
    ], stdout=subprocess.PIPE)

    writer = subprocess.Popen([
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{cw}x{ch}", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        out_path, "-loglevel", "error",
    ], stdin=subprocess.PIPE)

    # source frame size: probe once via ffprobe-free trick - read from ffmpeg stderr is
    # fragile, so just hardcode 1920x1080 (this pipeline's known source resolution).
    sw, sh = 1920, 1080
    frame_bytes = sw * sh * 3

    for i in range(n_frames):
        raw = reader.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break
        frame = Image.frombytes("RGB", (sw, sh), raw)

        t = i / max(n_frames - 1, 1)
        u = ease(t)
        cx, cy = lerp(fx, tx, u), lerp(fy, ty, u)
        cwid, chei = lerp(fw, tw, u), lerp(fh, th, u)
        crop = frame.crop((int(cx), int(cy), int(cx + cwid), int(cy + chei)))

        scale = cw / crop.width
        sh_ = max(1, int(crop.height * scale))
        resized = crop.resize((cw, sh_), Image.LANCZOS)

        amp = 45.0 * (u ** 2)  # violent shake ramps up, negligible at the start
        hz = 25.0
        w = 2 * math.pi * hz * t * (end - start)
        dx = amp * (0.6 * math.sin(w) + 0.4 * math.sin(2.7 * w + 1.3))
        dy = amp * (0.6 * math.sin(1.31 * w + 0.7) + 0.4 * math.sin(3.1 * w + 2.1))

        canvas = Image.new("RGB", (cw, ch), (0, 0, 0))
        px = int((cw - cw) / 2 + dx)
        py = int((ch - sh_) / 2 + dy)
        canvas.paste(resized, (px, py))

        writer.stdin.write(canvas.tobytes())
        if i % 30 == 0:
            print(f"frame {i}/{n_frames}")

    reader.stdout.close()
    reader.wait()
    writer.stdin.close()
    writer.wait()
    print("wrote", out_path)


if __name__ == "__main__":
    main()
