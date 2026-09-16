"""Build a word-accurate .srt for an edited timeline whose clips come from
more than one source file, using an occurrences list straight from the
Resolve timeline (source_range_report shape: video track-1 entries with
`key` (source path), `timeline_range` (record frames, timeline-start-relative),
`source_range` (source frames)).

Usage: build_srt_multi_source.py <occurrences.json> <fps> <out.srt> \
    <source_path>=<words.json> [<source_path>=<words.json> ...]
"""
import json
import sys

MAX_CHUNK_WORDS = 10
MAX_CHUNK_SECONDS = 4.0
GAP_BREAK_SECONDS = 1.0


def srt_timecode(t):
    if t < 0:
        t = 0
    ms = round(t * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    occ_path, fps_str, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    fps = float(fps_str)

    words_by_source = {}
    for pair in sys.argv[4:]:
        src, words_path = pair.split("=", 1)
        words_by_source[src] = json.load(open(words_path, encoding="utf-8"))

    occ = json.load(open(occ_path, encoding="utf-8"))
    items = [o for o in occ if o["track_type"] == "video" and o["track_index"] == 1]
    items.sort(key=lambda o: o["timeline_range"][0])

    timeline_start = min(o["timeline_range"][0] for o in items)

    mapped = []
    for occ_index, o in enumerate(items):
        src = o["key"]
        full = words_by_source.get(src)
        if full is None:
            continue
        sf0, sf1 = o["source_range"]
        rf0, rf1 = o["timeline_range"]
        rf0 -= timeline_start
        rf1 -= timeline_start
        for fseg in full["segments"]:
            for w in fseg.get("words", []):
                if "start" not in w or "end" not in w:
                    continue
                wsf = w["start"] * fps
                wef = w["end"] * fps
                overlap = min(wef, sf1) - max(wsf, sf0)
                word_dur = wef - wsf
                # keep a word if most of it survived the cut, clamped to the
                # clip's actual boundaries so it never describes trimmed audio
                if overlap > 0 and overlap >= 0.5 * word_dur:
                    csf = max(wsf, sf0)
                    cef = min(wef, sf1)
                    new_start = (rf0 + (csf - sf0)) / fps
                    new_end = (rf0 + (cef - sf0)) / fps
                    mapped.append({
                        "start": new_start,
                        "end": new_end,
                        "text": w.get("word", "").strip(),
                        "occ": occ_index,
                    })

    mapped.sort(key=lambda x: x["start"])

    chunks = []
    cur = []
    for w in mapped:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            dur = w["end"] - cur[0]["start"]
            clip_changed = w["occ"] != cur[-1]["occ"]
            if clip_changed or gap > GAP_BREAK_SECONDS or len(cur) >= MAX_CHUNK_WORDS or dur > MAX_CHUNK_SECONDS:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    with open(out_path, "w", encoding="utf-8") as f:
        for i, chunk in enumerate(chunks, 1):
            start = chunk[0]["start"]
            end = chunk[-1]["end"]
            text = " ".join(w["text"] for w in chunk)
            f.write(f"{i}\n{srt_timecode(start)} --> {srt_timecode(end)}\n{text}\n\n")

    print(f"wrote {len(chunks)} subtitle chunks from {len(mapped)} mapped words to {out_path}")


if __name__ == "__main__":
    main()
