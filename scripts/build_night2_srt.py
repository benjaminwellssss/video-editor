"""One-off SRT builder for the 09-17-2026 edit: teaser (3 disjoint raw
sub-clips concatenated), intro (single raw window), main body (clip_infos
list, raw frames), outro (single raw window). All map back to one words.json.

Usage: build_night2_srt.py <words.json> <main_body_clip_infos.json> <out.srt>
"""
import json
import sys

FPS = 30.0
TEASER_WINDOWS = []
INTRO_WINDOWS = [(0.5, 18.5), (431.2, 464.8)]
OUTRO_RAW = (10511.0, 10553.467)

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
    words_path, clip_infos_path, out_path = sys.argv[1:4]
    full = json.load(open(words_path, encoding="utf-8"))
    main_body = json.load(open(clip_infos_path, encoding="utf-8"))

    raw_words = []
    for seg in full["segments"]:
        for w in seg.get("words", []):
            if "start" in w and "end" in w:
                raw_words.append(w)
    raw_words.sort(key=lambda w: w["start"])

    mapped = []

    # intro: 2 disjoint sub-clips (knock-knock cold open + welcome), own
    # internal clock, concatenated
    intro_record = 0.0
    for i, (a, b) in enumerate(INTRO_WINDOWS):
        for w in raw_words:
            if a <= w["start"] and w["end"] <= b:
                mapped.append({
                    "start": intro_record + (w["start"] - a),
                    "end": intro_record + (w["end"] - a),
                    "text": w["word"].strip(),
                    "occ": f"intro{i}",
                })
        intro_record += b - a
    offset = intro_record

    # main body: clip_infos raw-frame ranges, clamped word overlap
    for i, c in enumerate(main_body):
        sf0, sf1 = c["start_frame"], c["end_frame"]
        rf0 = c["record_frame"] / FPS + offset
        for w in raw_words:
            wsf, wef = w["start"] * FPS, w["end"] * FPS
            overlap = min(wef, sf1) - max(wsf, sf0)
            word_dur = wef - wsf
            if overlap > 0 and word_dur > 0 and overlap >= 0.5 * word_dur:
                csf, cef = max(wsf, sf0), min(wef, sf1)
                mapped.append({
                    "start": rf0 + (csf - sf0) / FPS,
                    "end": rf0 + (cef - sf0) / FPS,
                    "text": w["word"].strip(),
                    "occ": f"main{i}",
                })

    main_body_end_record = main_body[-1]["record_frame"] + (
        main_body[-1]["end_frame"] - main_body[-1]["start_frame"]
    )
    outro_record_start = offset + main_body_end_record / FPS

    # outro: direct offset
    for w in raw_words:
        if OUTRO_RAW[0] <= w["start"] and w["end"] <= OUTRO_RAW[1]:
            mapped.append({
                "start": outro_record_start + (w["start"] - OUTRO_RAW[0]),
                "end": outro_record_start + (w["end"] - OUTRO_RAW[0]),
                "text": w["word"].strip(),
                "occ": "outro",
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
