"""Build a word-accurate .srt for an edited timeline, from its clip_infos cut
list and the full-source word-level transcript.

Maps each transcript word through the cut's (start_frame, end_frame,
record_frame) ranges onto the final timeline, keeping only words that fall
fully inside a single kept range, then groups words into readable subtitle
chunks (gap-based, like natural reading pace).

Usage: build_srt_from_cut.py <clip_infos.json> <full_words.json> <fps> <out.srt>
"""
import json
import sys

MAX_CHUNK_WORDS = 10
MAX_CHUNK_SECONDS = 4.0
GAP_BREAK_SECONDS = 1.0


def clean_word(w):
    return w.strip()


def srt_timecode(t):
    if t < 0:
        t = 0
    ms = round(t * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    cut_path, words_path, fps_str, out_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    fps = float(fps_str)
    cut = json.load(open(cut_path, encoding="utf-8"))
    full = json.load(open(words_path, encoding="utf-8"))

    # only ranges with meaningful duration matter for words (skip 1-2 frame
    # fade micro-clips implicitly — no word will ever fall inside a 2-frame span)
    ranges = [(c["start_frame"], c["end_frame"], c["record_frame"]) for c in cut]

    mapped = []
    for fseg in full["segments"]:
        for w in fseg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            wsf = w["start"] * fps
            wef = w["end"] * fps
            for sf, ef, rf in ranges:
                if wsf >= sf and wef <= ef:
                    new_start = (rf + (wsf - sf)) / fps
                    new_end = (rf + (wef - sf)) / fps
                    mapped.append({"start": new_start, "end": new_end, "text": clean_word(w.get("word", ""))})
                    break

    mapped.sort(key=lambda x: x["start"])

    chunks = []
    cur = []
    for w in mapped:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            dur = w["end"] - cur[0]["start"]
            if gap > GAP_BREAK_SECONDS or len(cur) >= MAX_CHUNK_WORDS or dur > MAX_CHUNK_SECONDS:
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
