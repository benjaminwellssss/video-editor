"""Build a jump-cut short like build_jumpcut_short.py, but with caller-supplied
gameplay/facecam crop filters instead of the hardcoded EP3/EP4-rig constants -
for a raw source with a different OBS layout.

Each segment is composited as its own ffmpeg call, then stitched with the
concat demuxer (stream copy) - same two-pass pattern as build_jumpcut_short.py,
for the same memory reasons.

Compositing is done with `overlay` onto a black 1080-wide canvas, not `vstack`.
Confirmed 2026-09-21: this machine's ffmpeg build (gyan.dev, built with
--disable-w32threads) segfaults on `vstack` with two cropped+scaled branches
of the same input - reproduced down to a minimal split+crop+scale+vstack
case, with matching widths, on a short 5s test clip, so it isn't about scale
mismatches or seeking into a large file. `overlay` with the same crop/scale
filters works fine. If a future ffmpeg upgrade fixes this, vstack would be
simpler, but don't switch back without testing.

Usage: build_custom_crop_short.py <segments.json> <raw_src> <out_mp4>
    <gameplay_filter> <facecam_filter> <facecam_height> [canvas_height]

gameplay_filter/facecam_filter: ffmpeg -filter_complex fragments (e.g.
"crop=960:1080:480:0,scale=1080:1215") that each produce 1080-wide output.
facecam_height: the facecam branch's scaled output height in px - needed to
know where to overlay the gameplay branch beneath it. canvas_height defaults
to 1920 (standard vertical short).

A segment may instead carry its own "full_facecam_filter" (an ffmpeg
-filter_complex fragment producing a full 1080x<canvas_height> frame on its
own, e.g. "crop=540:960:780:70,scale=1080:1920") to bypass the split layout
entirely for that segment - for a direct-to-camera moment recorded with the
facecam window resized/recentred instead of docked in its usual gameplay
corner (its own crop, verified separately; don't assume it matches the
gameplay-segment facecam box).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CANVAS_W = 1080


def main():
    segments_path, raw_src, out_path, gameplay_filter, facecam_filter = sys.argv[1:6]
    facecam_height = int(sys.argv[6])
    canvas_height = int(sys.argv[7]) if len(sys.argv) > 7 else 1920
    segments = json.loads(Path(segments_path).read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        part_paths = []
        for i, seg in enumerate(segments):
            start, end = seg["start"], seg["end"]
            dur = end - start
            part_path = tmp / f"part{i}.mp4"
            print(f"compositing segment {i+1}/{len(segments)} ({start}-{end}, {dur:.1f}s)")
            full_filter = seg.get("full_facecam_filter")
            if full_filter:
                filter_complex = f"[0:v]{full_filter}[outv]"
            else:
                filter_complex = (
                    f"color=c=black:s={CANVAS_W}x{canvas_height}:d={dur}:r=30[bg];"
                    f"[0:v]{gameplay_filter}[gameplay];"
                    f"[0:v]{facecam_filter}[facecam];"
                    f"[bg][facecam]overlay=0:0[tmp];"
                    f"[tmp][gameplay]overlay=0:{facecam_height}[outv]"
                )
            cmd = [
                "ffmpeg", "-nostdin", "-y", "-ss", str(start), "-i", raw_src, "-t", str(dur),
                "-filter_complex", filter_complex,
                "-map", "[outv]", "-map", "0:a:0",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                str(part_path), "-loglevel", "error",
            ]
            subprocess.run(cmd, check=True)
            part_paths.append(part_path)

        list_path = tmp / "list.txt"
        list_path.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p in part_paths), encoding="utf-8"
        )
        total = sum(seg["end"] - seg["start"] for seg in segments)
        print(f"total kept duration: {total:.2f} s across {len(segments)} segments")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c", "copy", out_path, "-loglevel", "error"],
            check=True,
        )
    print("wrote", out_path)


if __name__ == "__main__":
    main()
