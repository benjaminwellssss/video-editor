"""Build a 9:16 short with the full-bleed-gameplay + facecam.exe-framed PiP
layout (2026-09-24 convention): gameplay fills the entire 1080x1920 canvas,
the facecam sits on top as a smaller framed window in the position given.

Composites each kept segment separately (small filter graph per segment),
then stitches with the concat demuxer (stream copy) - the established
jump-cut pattern that avoids the "Cannot allocate memory" filter_complex bug
on this machine. Audio comes from the same source file (use the 433ms-
sync-corrected synced_master.mp4, never the raw VOD directly).

Usage: python build_fullbleed_short.py <segments.json> <source.mp4> <out.mp4> <frame.png> <facecam_w> <facecam_h> <facecam_x> <facecam_y>

segments.json: [{"start": s, "end": e}, ...] in source-file seconds.
frame.png: the facecam.exe chrome asset (from render_facecam_frame.py),
  already sized so its content cutout matches facecam_w x facecam_h.
facecam_x/y: where the FRAME's top-left corner sits on the 1080x1920 canvas
  (the video content itself is offset further in by the frame's own cutout
  margin - this script reads that offset back out of the frame image by
  re-deriving it the same way render_facecam_frame.py computed it).
"""
import json
import subprocess
import sys
import os

W, H = 1080, 1920


def cutout_offset(content_w):
    scale = content_w / 446.0
    border = max(2, round(2 * scale))
    pad = max(2, round(3 * scale))
    titlebar_h = max(18, round(26 * scale))
    margin = max(2, round(3 * scale))
    cutout_x = margin + pad + border
    cutout_y = margin + pad + titlebar_h + round(3 * scale) + border
    return cutout_x, cutout_y


def main():
    segs_path, src, out_path, frame_png, fw, fh, fx, fy = sys.argv[1:9]
    fw, fh, fx, fy = int(fw), int(fh), int(fx), int(fy)
    segments = json.load(open(segs_path))

    ox, oy = cutout_offset(fw)
    vid_x, vid_y = fx + ox, fy + oy

    workdir = os.path.dirname(out_path)
    list_path = os.path.join(workdir, os.path.basename(out_path) + "_list.txt")
    seg_paths = []

    for i, seg in enumerate(segments):
        s, e = seg["start"], seg["end"]
        seg_out = os.path.join(workdir, f"{os.path.basename(out_path)}_seg{i}.mp4")
        filt = (
            f"[0:v]crop={1920}:{1080}:0:0,scale=3413:1920,crop=1080:1920:(in_w-1080)/2:0[gameplay];"
            f"[0:v]crop=460:342:1460:738,scale=1080:803,crop=1080:660:0:71,scale={fw}:{fh}[facecam];"
            f"[gameplay][facecam]overlay={vid_x}:{vid_y}[withface];"
            f"[withface][1:v]overlay={fx}:{fy}[outv]"
        )
        cmd = [
            "ffmpeg", "-y", "-ss", str(s), "-to", str(e), "-i", src,
            "-i", frame_png,
            "-filter_complex", filt, "-map", "[outv]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-r", "30",
            "-c:a", "aac", "-b:a", "192k",
            seg_out, "-loglevel", "error",
        ]
        print("building segment", i, s, "-", e)
        subprocess.run(cmd, check=True)
        seg_paths.append(seg_out)

    with open(list_path, "w") as f:
        for p in seg_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", out_path, "-loglevel", "error",
    ], check=True)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
