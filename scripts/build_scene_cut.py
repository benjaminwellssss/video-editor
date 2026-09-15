"""Build a dead-air-trimmed clip_infos payload from a list of scene windows.

For each scene (start,end) in raw VOD seconds, finds internal transcript gaps
above GAP_THRESHOLD and trims them down to BUFFER_S on each side (leaves
natural breathing room, doesn't delete the pause outright), the same
transcript-gap method used for the main-cut dead-air trim on prior jobs.

Usage: build_scene_cut.py <scenes.json> <full_words.json> <fps> <clip_id> <out.json>

scenes.json: [{"start": float, "end": float}, ...] in raw VOD seconds.
"""
import json
import sys

GAP_THRESHOLD = 2.0  # seconds of silence inside a scene before trimming it
BUFFER_S = 1.0        # seconds kept on each side of a trimmed gap


def get_words_in_range(full, a, b):
    words = []
    for seg in full["segments"]:
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            if a <= w["start"] <= b:
                words.append((w["start"], w["end"]))
    words.sort()
    return words


def trim_scene(a, b, words):
    """Return a list of (start,end) sub-ranges within [a,b] with internal
    dead-air gaps collapsed to BUFFER_S."""
    if not words:
        return [(a, b)]
    ranges = []
    cur_start = a
    prev_end = a
    for ws, we in words:
        gap = ws - prev_end
        if gap > GAP_THRESHOLD:
            ranges.append((cur_start, prev_end + BUFFER_S))
            cur_start = ws - BUFFER_S
        prev_end = we
    ranges.append((cur_start, min(b, prev_end + BUFFER_S)))
    return ranges


def main():
    scenes_path, words_path, fps_str, clip_id, out_path = sys.argv[1:6]
    fps = float(fps_str)
    scenes = json.load(open(scenes_path, encoding="utf-8"))
    full = json.load(open(words_path, encoding="utf-8"))

    clip_infos = []
    record_frame = 0
    total_kept = 0.0
    for scene in scenes:
        a, b = scene["start"], scene["end"]
        words = get_words_in_range(full, a, b)
        sub_ranges = trim_scene(a, b, words)
        for rs, re_ in sub_ranges:
            dur = re_ - rs
            if dur <= 0:
                continue
            start_frame = round(rs * fps)
            end_frame = round(re_ * fps)
            clip_infos.append({
                "clip_id": clip_id,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "record_frame": record_frame,
            })
            record_frame += end_frame - start_frame
            total_kept += dur

    json.dump(clip_infos, open(out_path, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"{len(scenes)} scenes -> {len(clip_infos)} kept sub-ranges, "
          f"{total_kept:.1f}s kept ({total_kept/60:.1f} min), "
          f"final record_frame end {record_frame}")


if __name__ == "__main__":
    main()
