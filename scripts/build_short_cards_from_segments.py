"""Build caption cards for a jump-cut short directly from the full-VOD word
transcript, mapped through the short's own (start,end) segment list.

Reuses the full-VOD WhisperX transcript rather than re-transcribing the
window in isolation — fine when the words in that window are already cleanly
separated in the full-VOD run (spot-check before trusting this for a window
that reads garbled/merged; if so, extract and re-transcribe that window in
isolation instead, per the short15 lesson).

Usage: <venv-python> build_short_cards_from_segments.py <segments.json> <full_words.json> <out_cards.json>

segments.json: [{"start": float, "end": float}, ...] in raw VOD seconds —
the exact jump-cut boundaries used to build the short's video.
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from build_caption_cards import clean_word, words_to_cards


def main():
    seg_path, words_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    segments = json.load(open(seg_path, encoding="utf-8"))
    full = json.load(open(words_path, encoding="utf-8"))

    raw_words = []
    for seg in full["segments"]:
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            raw_words.append(w)
    raw_words.sort(key=lambda w: w["start"])

    mapped = []
    offset = 0.0
    for s in segments:
        a, b = s["start"], s["end"]
        for w in raw_words:
            if w["start"] >= a and w["end"] <= b:
                clean = clean_word(w.get("word", ""))
                if not clean:
                    continue
                mapped.append({
                    "start": offset + (w["start"] - a),
                    "end": offset + (w["end"] - a),
                    "text": clean,
                })
        offset += b - a

    cards = words_to_cards(mapped)
    json.dump(cards, open(out_path, "w", encoding="utf-8"), indent=2)
    total_dur = cards[-1]["end"] if cards else 0
    print(f"{len(cards)} cards from {len(mapped)} mapped words, last card ends {total_dur:.1f}s")


if __name__ == "__main__":
    main()
