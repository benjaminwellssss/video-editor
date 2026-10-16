"""Cut the stretches marked with the caption editor's Trim tool out of a finished (captioned) short.

Usage: python apply_trims.py <video.mp4> <speakers.json> <out.mp4>

The editor saves trims as "trims": [[start, end], ...] (seconds on the clip's own timeline) in the speakers
sidecar. Captions keep their original times, so render and composite the captions first, then run this on
the composited video: the trimmed stretches go from picture and sound together and nothing drifts.
Exits without writing anything when there are no trims.
"""
import json
import subprocess
import sys


def keep_expr(trims):
    return "not(" + "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in trims) + ")"


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout)


def main():
    src, sidecar, out = sys.argv[1], sys.argv[2], sys.argv[3]
    trims = sorted([float(a), float(b)] for a, b in json.load(open(sidecar, encoding="utf-8")).get("trims", []) if float(b) > float(a))
    if not trims:
        print("no trims in", sidecar)
        return
    keep = keep_expr(trims)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src,
                    "-vf", f"select='{keep}',setpts=N/FRAME_RATE/TB",
                    "-af", f"aselect='{keep}',asetpts=N/SR/TB",
                    "-c:v", "h264_nvenc", "-preset", "p6", "-cq", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], check=True)
    before, after = duration(src), duration(out)
    removed = sum(b - a for a, b in trims)
    print(f"trimmed {len(trims)} stretch(es), {removed:.2f}s: {before:.2f}s -> {after:.2f}s")
    assert abs((before - removed) - after) < 0.15, "output length doesn't match the trims - check the result"


if __name__ == "__main__":
    assert keep_expr([[1, 2], [3.5, 4]]) == "not(between(t,1.000,2.000)+between(t,3.500,4.000))"
    main()
