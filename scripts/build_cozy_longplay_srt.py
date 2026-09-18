"""One-off SRT builder for the 09-16-2026 cozy-longplay edit: intro and outro
are separate pre-rendered clips (their own internal clock, offset from the
raw VOD), the main body is a list of raw-frame clip_infos ranges. All three
map back to the same words.json (raw VOD seconds).

Usage: build_cozy_longplay_srt.py <words.json> <main_body_clip_infos.json> <out.srt>
"""
import json
import sys

FPS = 30.0
INTRO_RAW_START = 3.0
INTRO_RAW_END = 66.2
OUTRO_RAW_START = 4394.0
OUTRO_RAW_END = 4454.789

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

    intro_frames = round((INTRO_RAW_END - INTRO_RAW_START) * FPS)
    main_body_end_record = main_body[-1]["record_frame"] + (
        main_body[-1]["end_frame"] - main_body[-1]["start_frame"]
    )
    outro_record_start = intro_frames + main_body_end_record

    mapped = []

    # intro: direct offset, own occurrence id 0
    for w in raw_words:
        if INTRO_RAW_START <= w["start"] and w["end"] <= INTRO_RAW_END:
            mapped.append({
                "start": w["start"] - INTRO_RAW_START,
                "end": w["end"] - INTRO_RAW_START,
                "text": w["word"].strip(),
                "occ": "intro",
            })

    # main body: walk clip_infos (raw frame ranges), same clamped-overlap rule
    # as build_srt_multi_source.py
    for i, c in enumerate(main_body):
        sf0, sf1 = c["start_frame"], c["end_frame"]
        rf0 = c["record_frame"] + intro_frames
        for w in raw_words:
            wsf, wef = w["start"] * FPS, w["end"] * FPS
            overlap = min(wef, sf1) - max(wsf, sf0)
            word_dur = wef - wsf
            if overlap > 0 and word_dur > 0 and overlap >= 0.5 * word_dur:
                csf, cef = max(wsf, sf0), min(wef, sf1)
                mapped.append({
                    "start": (rf0 + (csf - sf0)) / FPS,
                    "end": (rf0 + (cef - sf0)) / FPS,
                    "text": w["word"].strip(),
                    "occ": f"main{i}",
                })

    # outro: direct offset by record start
    for w in raw_words:
        if OUTRO_RAW_START <= w["start"] and w["end"] <= OUTRO_RAW_END:
            mapped.append({
                "start": outro_record_start / FPS + (w["start"] - OUTRO_RAW_START),
                "end": outro_record_start / FPS + (w["end"] - OUTRO_RAW_START),
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
