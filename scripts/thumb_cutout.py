"""Thumbnail cutout without redrawing the face: 4x upscale, cut out the person, put him on pure white.

Usage: python thumb_cutout.py <cap.png> [<cap.png> ...] [--out <dir>] [--model birefnet-portrait] [--no-upscale]

--no-upscale cuts out the cap at its own size (the user found the 4x upscale of a tiny facecam face
too soft, 2026-10-17). Both steps keep the real pixels (no generative face): Real-ESRGAN's general photo model (not a face-restore
one) enlarges the cap, then rembg's portrait segmentation cuts the man out of the ENLARGED image, which gives
cleaner hair edges than cutting at 469x264. Writes <name>_white.png (flat #FFFFFF, for Illustrator's image trace
or Photoshop) and <name>_cutout.png (transparent). Run it with the thumb venv's python (needs rembg + cv2);
the upscaler is the Real-ESRGAN ncnn build unpacked next to it.
"""
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from rembg import new_session, remove

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "video-editor")
ESRGAN = os.path.join(CACHE, "realesrgan", "realesrgan-ncnn-vulkan.exe")


def upscale(src, dst):
    subprocess.run([ESRGAN, "-i", src, "-o", dst, "-n", "realesrgan-x4plus", "-s", "4"], check=True, capture_output=True)


LIME = (155, 255, 46)  # signature sticker outline, RGB


def sticker(rgba):
    """Channel signature: white inner ring + lime outer ring around the cutout, both blurred so they blend
    into the background like a glow. Rings scale with the image so every thumbnail's sticker looks the same;
    no padding at the bottom, where the body bleeds off."""
    h, w = rgba.shape[:2]
    white_r, lime_r = max(2, round(h * 0.018)), max(2, round(h * 0.040))
    white_s, lime_s = white_r * 0.35, lime_r * 0.5  # blur sigmas: soft white edge, glowing lime edge
    pad = lime_r + round(3 * lime_s) + 2
    a = np.zeros((h + pad, w + 2 * pad), np.uint8)
    a[pad:, pad:pad + w] = rgba[:, :, 3]
    solid = (a > 128).astype(np.uint8) * 255
    grow = lambda r, sig: cv2.GaussianBlur(cv2.dilate(solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1,) * 2)), (0, 0), sig)
    out = np.zeros((h + pad, w + 2 * pad, 4), np.float32); out[:, :, :3] = LIME  # straight (not premultiplied) colour under the glow
    for ring, rgb in ((grow(lime_r, lime_s), LIME), (grow(white_r, white_s), (255, 255, 255))):
        f = ring[:, :, None].astype(np.float32) / 255
        out[:, :, :3] = out[:, :, :3] * (1 - f) + np.array(rgb, np.float32) * f
        out[:, :, 3:] = np.maximum(out[:, :, 3:], f * 255)
    f = a[:, :, None].astype(np.float32) / 255
    body = np.zeros_like(out[:, :, :3]); body[pad:, pad:pad + w] = rgba[:, :, :3]
    out[:, :, :3] = out[:, :, :3] * (1 - f) + body * f
    return out.astype(np.uint8)


def main():
    args = sys.argv[1:]
    out = args[args.index("--out") + 1] if "--out" in args else None
    model = args[args.index("--model") + 1] if "--model" in args else "birefnet-portrait"
    files = [a for i, a in enumerate(args) if a.lower().endswith((".png", ".jpg", ".jpeg"))
             and not (i and args[i - 1] in ("--out", "--model"))]
    session = new_session(model)
    for f in files:
        d = out or os.path.dirname(os.path.abspath(f))
        os.makedirs(d, exist_ok=True)
        base = os.path.splitext(os.path.basename(f))[0]
        if "--no-upscale" in args:
            rgb = cv2.imread(f)
        else:
            with tempfile.TemporaryDirectory() as t:
                big = os.path.join(t, "big.png")
                upscale(f, big)
                rgb = cv2.imread(big)
        rgba = remove(cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB), session=session)  # H x W x 4, RGBA
        alpha = rgba[:, :, 3:4].astype(np.float32) / 255
        white = (rgba[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
        cv2.imwrite(os.path.join(d, base + "_white.png"), cv2.cvtColor(white, cv2.COLOR_RGB2BGR))
        cv2.imwrite(os.path.join(d, base + "_cutout.png"), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
        st = sticker(rgba)
        ys, xs = np.nonzero(st[:, :, 3])  # crop to the sticker so it drops into a thumbnail at its real size
        st = st[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        cv2.imwrite(os.path.join(d, base + "_sticker.png"), cv2.cvtColor(st, cv2.COLOR_RGBA2BGRA))
        print(f"  {base}: {rgb.shape[1]}x{rgb.shape[0]} -> {base}_white.png, {base}_cutout.png, {base}_sticker.png", flush=True)


if __name__ == "__main__":
    a = np.array([[[200, 100, 50, 128]]], np.uint8)  # half-transparent pixel blends halfway to white
    f = a[:, :, 3:4].astype(np.float32) / 255
    assert (a[:, :, :3] * f + 255 * (1 - f)).astype(np.uint8)[0, 0, 0] == 227
    s = np.zeros((500, 500, 4), np.uint8); s[200:, 200:300] = (10, 20, 30, 255)
    st = sticker(s)  # body kept, white ring next to it, lime ring outside that, nothing below the bottom edge
    p = 20 + 30 + 2  # pad at h=500: lime_r + 3 * lime sigma + 2
    near = lambda px, rgb: max(abs(int(a) - b) for a, b in zip(px, rgb)) < 40
    assert st.shape[0] == 500 + p and tuple(st[-1, 250 + p, :3]) == (10, 20, 30)
    assert near(st[-1, 200 + p - 3, :3], (255, 255, 255)) and near(st[-1, 200 + p - 15, :3], LIME)
    assert 0 < st[-1, 200 + p - 24, 3] < 128 and st[-1, 200 + p - 50, 3] == 0  # lime fades out, doesn't stop hard
    main()
