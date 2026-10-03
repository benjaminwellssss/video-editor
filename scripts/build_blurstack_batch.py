"""Build finished 1080x1920 shorts (no captions) in the blur-stack layout the
user approved on 2026-09-30: blurred zoomed copy of the gameplay as background,
sharp gameplay foreground, facecam.exe window on top, then the handles overlay.
Equivalent to the 16:9 Resolve recipe (V1 blur zoom 2.12 / V2 gameplay zoom 0.84
tilt -88 / V3 facecam crop+pan) followed by the centered 608x1080 crop to 9:16.

Each segment is composited on its own, the segments are joined with the concat
demuxer (stream copy), then one final pass adds the handle overlay (so its
animation runs once across the whole clip, not once per segment).

Usage: python build_blurstack_batch.py <spec.json> [name ...]

spec.json:
{
  "source": "...mp4", "audio_stream": 0,
  "out_dir": "...", "work_dir": "...",
  "handle": "...gif",
  "face_crop": [w, h, x, y],       # facecam.exe window in the 1920x1080 source
  "fg_height": 1080,               # source rows used for the foreground (cut off a bottom ticker)
  "fg_bottom_aligned": false,      # true: foreground bottom sits on the canvas bottom
  "clips": [{"name": "...", "segments": [[start_s, end_s], ...]}]
}
Writes <out_dir>/<name>/<name>.mp4 for each clip (skips ones that already exist).
"""
import json
import os
import subprocess
import sys

FG_W_SRC = 723      # source columns shown in the foreground (1080 / 1.4933)
FACE_OUT_W = 821
FACE_X, FACE_Y = 133, 6
FG_Y_DEFAULT = 310
BG_CROP = (287, 510)  # source px magnified to the full 1080x1920 canvas


def run(cmd):
    subprocess.run(cmd, check=True)


def build_segment(spec, s, e, out):
    fw, fh, fx, fy = spec["face_crop"]
    fg_h = spec.get("fg_height", 1080)
    fg_scaled_h = round(fg_h * 1080 / FG_W_SRC / 2) * 2
    fg_y = 1920 - fg_scaled_h if spec.get("fg_bottom_aligned") else FG_Y_DEFAULT
    filt = (
        f"[0:v]split=3[a][b][c];"
        f"[a]crop={BG_CROP[0]}:{BG_CROP[1]}:(iw-{BG_CROP[0]})/2:(ih-{BG_CROP[1]})/2,"
        f"scale=270:480,gblur=sigma=8,scale=1080:1920:flags=bilinear[bg];"
        f"[b]crop={FG_W_SRC}:{fg_h}:(iw-{FG_W_SRC})/2:0,scale=1080:{fg_scaled_h}[fg];"
        f"[c]crop={fw}:{fh}:{fx}:{fy},scale={FACE_OUT_W}:-2[face];"
        f"[bg][fg]overlay=0:{fg_y}[t1];[t1][face]overlay={FACE_X}:{FACE_Y}[outv]"
    )
    run([
        "ffmpeg", "-y", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", spec["source"],
        "-filter_complex", filt, "-map", "[outv]", "-map", f"0:a:{spec.get('audio_stream', 0)}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        out, "-loglevel", "error",
    ])


def build_clip(spec, clip):
    name = clip["name"]
    out_dir = os.path.join(spec["out_dir"], name)
    final = os.path.join(out_dir, name + ".mp4")
    if os.path.exists(final):
        print("skip (exists):", name)
        return
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(spec["work_dir"], name)
    os.makedirs(work, exist_ok=True)
    seg_paths = []
    for i, (s, e) in enumerate(clip["segments"]):
        p = os.path.join(work, f"seg{i:02d}.mp4")
        build_segment(spec, s, e, p)
        seg_paths.append(p)
    lst = os.path.join(work, "list.txt")
    with open(lst, "w") as f:
        for p in seg_paths:
            f.write("file '" + p.replace("\\", "/") + "'\n")
    base = os.path.join(work, "base.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", base, "-loglevel", "error"])
    tmp = final + ".part.mp4"
    run([
        "ffmpeg", "-y", "-i", base, "-i", spec["handle"], "-filter_complex",
        "[1:v]scale=660:-1[h];[0:v][h]overlay=W-w-24:1600-h/2:enable='gte(t,3)'[outv]",
        "-map", "[outv]", "-map", "0:a", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-r", "30", "-movflags", "+faststart",
        tmp, "-loglevel", "error",
    ])
    os.replace(tmp, final)
    for p in seg_paths + [lst, base]:
        os.remove(p)
    os.rmdir(work)
    print("built:", final)


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    only = set(sys.argv[2:])
    os.makedirs(spec["work_dir"], exist_ok=True)
    for clip in spec["clips"]:
        if only and clip["name"] not in only:
            continue
        build_clip(spec, clip)


if __name__ == "__main__":
    main()
