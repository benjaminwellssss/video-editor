"""Build a jump-cut short like build_jumpcut_short.py, but with caller-supplied
gameplay/facecam crop filters instead of the hardcoded EP3/EP4-rig constants -
for a raw source with a different OBS layout.

Each segment is composited as its own ffmpeg call, then stitched with the
concat demuxer (stream copy) - same two-pass pattern as build_jumpcut_short.py,
for the same memory reasons.

Usage: build_custom_crop_short.py <segments.json> <raw_src> <out_mp4> <gameplay_filter> <facecam_filter>
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    segments_path, raw_src, out_path, gameplay_filter, facecam_filter = sys.argv[1:6]
    segments = json.loads(Path(segments_path).read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        part_paths = []
        for i, seg in enumerate(segments):
            start, end = seg["start"], seg["end"]
            dur = end - start
            part_path = tmp / f"part{i}.mp4"
            print(f"compositing segment {i+1}/{len(segments)} ({start}-{end}, {dur:.1f}s)")
            cmd = [
                "ffmpeg", "-y", "-ss", str(start), "-i", raw_src, "-t", str(dur),
                "-filter_complex",
                f"[0:v]{gameplay_filter}[gameplay];"
                f"[0:v]{facecam_filter}[facecam];"
                f"[facecam][gameplay]vstack=inputs=2[outv]",
                "-map", "[outv]", "-map", "0:a",
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
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c", "copy", out_path, "-loglevel", "error"],
            check=True,
        )
    print("wrote", out_path)


if __name__ == "__main__":
    main()
