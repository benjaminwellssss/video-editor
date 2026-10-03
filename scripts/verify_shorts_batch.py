"""Verify a built shorts batch against its buildspec: every clip exists as
<out_dir>/<name>/<name>.mp4 (renaming a leftover <name>.mp4.part.mp4 if it is a
complete valid file), is 1080x1920 with an audio stream, and its duration matches
the planned segment total (+/- 1.5s).

Usage: python verify_shorts_batch.py <buildspec.json>
"""
import json
import os
import subprocess
import sys


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_entries",
         "stream=codec_type,width,height", "-of", "json", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    d = json.loads(r.stdout)
    types = [s["codec_type"] for s in d["streams"]]
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    return float(d["format"]["duration"]), types, v.get("width"), v.get("height")


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    bad = 0
    for clip in spec["clips"]:
        name = clip["name"]
        d = os.path.join(spec["out_dir"], name)
        final = os.path.join(d, name + ".mp4")
        part = final + ".part.mp4"
        if not os.path.exists(final) and os.path.exists(part):
            if probe(part):
                os.replace(part, final)
                print("renamed leftover part ->", name)
        expected = sum(e - s for s, e in clip["segments"])
        info = probe(final) if os.path.exists(final) else None
        problems = []
        if not info:
            problems.append("missing/unreadable")
        else:
            dur, types, w, h = info
            if (w, h) != (1080, 1920):
                problems.append(f"size {w}x{h}")
            if "audio" not in types:
                problems.append("no audio")
            if abs(dur - expected) > 1.5:
                problems.append(f"duration {dur:.1f} vs planned {expected:.1f}")
        for f in ("captions.json", "captions.srt", "metadata.txt"):
            if not os.path.exists(os.path.join(d, f)):
                problems.append("missing " + f)
        if problems:
            bad += 1
        print(("BAD " if problems else "ok  ") + name + (f"  {info[0]:.1f}s" if info else ""), "; ".join(problems))
    print("problems:", bad, "of", len(spec["clips"]))


if __name__ == "__main__":
    main()
