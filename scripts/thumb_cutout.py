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
        print(f"  {base}: {rgb.shape[1]}x{rgb.shape[0]} -> {base}_white.png, {base}_cutout.png", flush=True)


if __name__ == "__main__":
    a = np.array([[[200, 100, 50, 128]]], np.uint8)  # half-transparent pixel blends halfway to white
    f = a[:, :, 3:4].astype(np.float32) / 255
    assert (a[:, :, :3] * f + 255 * (1 - f)).astype(np.uint8)[0, 0, 0] == 227
    main()
