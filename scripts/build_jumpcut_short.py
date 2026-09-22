"""Build a vertical short as a jump-cut concatenation of multiple raw-VOD segments.

Composites facecam (top, enlarged/centered, overlap-safe seam) over gameplay
(bottom) using the corrected layout, with Track1-only audio, from a list of
kept (start,end) segments in raw-VOD absolute seconds.

Each segment is composited as its OWN ffmpeg call (small filter graph, low
memory) and written to a temp file; the finished per-segment clips are then
stitched with the concat demuxer (stream copy, no re-encoding). A single
mega filter_complex across all segments reliably hit "Cannot allocate
memory" on this machine even for a 4-segment/23s short — this two-pass
approach is what actually works.

Usage: build_jumpcut_short.py <segments.json> <raw_src> <out_mp4>

segments.json: [{"start": float, "end": float, "punch": {...}?,
"layout": "split"|"facecam_full"?}, ...] in raw VOD seconds, already
buffered/trimmed by the caller (this script does not add buffers).

"punch" adds a brief whole-frame punch-in zoom at a specific beat within
that segment — see PUNCH DEFAULTS below. Use sparingly (one punch per short
at most, on the single funniest beat) — this replicates the "dynamic zoom
used sparingly" technique seen on reference channels, as a whole-frame
push-in rather than their more elaborate facecam/gameplay layout swap.

punch fields (all but "at" optional, defaults below):
  at       - seconds from THIS SEGMENT's own start where the zoom peaks
             (usually right on the punchline word)
  scale    - peak zoom factor, e.g. 1.15 = 15% punch-in (default 1.15)
  attack   - seconds to ramp from 1.0 up to peak scale (default 0.25)
  hold     - seconds to hold at peak scale (default 0.3)
  release  - seconds to ease back down to 1.0 (default 0.35)

"layout": "facecam_full" makes that whole segment a full-screen facecam
takeover instead of the normal split (no gameplay visible) — for a moment
where the subject is looking straight at the camera, talking or reacting
directly to the audience. Make this its OWN short segment (a few seconds,
carved out of the surrounding split-layout footage at the same source
timestamps) rather than a sub-window inside a split segment — it's a hard
cut in and a hard cut back out, matching "hold it for a beat before cutting
back to original vertical layout": build three segments (split, then
facecam_full for the reaction beat, then split again) instead of trying to
animate the transition.
"""
import json
import os
import subprocess
import sys
import tempfile


# The raw recording has a 22px solid-black letterbox bar baked into its very
# top row (y=0-21, full width) — a genuine artifact of the source, confirmed
# via direct pixel inspection, not a compositing bug. GAMEPLAY_CROP skips it
# (y=24 start, small safety margin) rather than capturing it as the top of
# the gameplay layer, which is what was actually producing the "black bar"
# at the facecam/gameplay seam — every previous "seam" fix (overlap padding,
# then vstack) addressed the wrong layer, since the true cause was never the
# compositing step at all. Re-check this offset if the OBS recording setup
# ever changes.
GAMEPLAY_CROP = "crop=911:1056:504:24,scale=1080:1260"
FACECAM_CROP = "crop=460:342:1460:738,scale=1080:803,crop=1080:660:0:71"
SEAM_Y = 660  # facecam height; gameplay is cropped/scaled to 1920-SEAM_Y, composited at this y

# Compositing uses `overlay` onto a black canvas, not `vstack`. Confirmed
# 2026-09-21: this machine's ffmpeg build (gyan.dev, --disable-w32threads)
# segfaults on vstack fed by two crop+scale branches of the same input, down
# to a minimal repro (matching widths, short clip, shallow seek — not a
# scale-mismatch or large-file-seek issue). overlay with identical filters
# works. Don't switch back to vstack without testing on this exact ffmpeg
# build first.

# Full-screen facecam takeover (for a direct-to-camera moment): crop a 9:16
# slice out of the same webcam box (full 342px height, centered 192px-wide
# slice — 342*9/16=192.4) and scale to fill the whole 1080x1920 canvas. This
# is necessarily a tight, zoomed-in crop since the source webcam box is only
# 460x342 (~4:3) — there's no wider facecam source to draw on. Re-check
# FACECAM_FULL_X if the subject isn't horizontally centered in their own
# webcam box on a different OBS layout.
FACECAM_FULL_CROP = "crop=192:342:1594:738,scale=1080:1920"

PUNCH_DEFAULTS = {"scale": 1.15, "attack": 0.25, "hold": 0.3, "release": 0.35}


def punch_zoom_filter(punch):
    """Whole-frame punch-in zoom: 1.0 -> scale -> 1.0 over attack/hold/release,
    centered on `at` (seconds within this segment's own trimmed timeline)."""
    p = {**PUNCH_DEFAULTS, **punch}
    at, scale, attack, hold, release = p["at"], p["scale"], p["attack"], p["hold"], p["release"]
    t0, t1, t2, t3 = at - attack, at, at + hold, at + hold + release
    envelope = (
        f"if(lt(t,{t0}),0,"
        f"if(lt(t,{t1}),(t-{t0})/{attack},"
        f"if(lt(t,{t2}),1,"
        f"if(lt(t,{t3}),1-(t-{t2})/{release},0))))"
    )
    zoom = f"(1+{scale - 1}*({envelope}))"
    return (
        f"crop=w='iw/{zoom}':h='ih/{zoom}':x='(iw-ow)/2':y='(ih-oh)/2',"
        f"scale=1080:1920"
    )


def build_segment(src, seg, out_path):
    dur = seg["end"] - seg["start"]
    if seg.get("layout") == "facecam_full":
        base = f"[0:v]{FACECAM_FULL_CROP}[base]"
    else:
        base = (
            f"color=c=black:s=1080x1920:d={dur}:r=30[bg];"
            f"[0:v]{GAMEPLAY_CROP}[gameplay];"
            f"[0:v]{FACECAM_CROP}[facecam];"
            f"[bg][facecam]overlay=0:0[tmp];"
            f"[tmp][gameplay]overlay=0:{SEAM_Y}[base]"
        )
    punch = seg.get("punch")
    if punch:
        filter_complex = f"{base};[base]{punch_zoom_filter(punch)}[outv]"
    else:
        filter_complex = f"{base};[base]null[outv]"

    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-ss", str(seg["start"]), "-t", str(dur), "-i", src,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        out_path, "-loglevel", "warning",
    ]
    r = subprocess.run(cmd)
    return r.returncode == 0


def main():
    seg_path, src, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    segments = json.load(open(seg_path, encoding="utf-8"))
    total_dur = sum(s["end"] - s["start"] for s in segments)

    with tempfile.TemporaryDirectory(prefix="jumpcut_") as tmpdir:
        seg_files = []
        for i, seg in enumerate(segments):
            seg_out = os.path.join(tmpdir, f"seg{i:02d}.mp4")
            print(f"compositing segment {i+1}/{len(segments)} "
                  f"({seg['start']}-{seg['end']}, {seg['end']-seg['start']:.1f}s)")
            if not build_segment(src, seg, seg_out):
                print(f"FAILED on segment {i}")
                sys.exit(1)
            seg_files.append(seg_out)

        list_path = os.path.join(tmpdir, "list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for sf in seg_files:
                f.write(f"file '{sf}'\n")

        cmd = [
            "ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", out_path, "-loglevel", "warning",
        ]
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print("concat FAILED")
            sys.exit(1)

    print("total kept duration:", round(total_dur, 2), "s across", len(segments), "segments")
    print("wrote", out_path)


if __name__ == "__main__":
    main()
