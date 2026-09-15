"""Remap full-VOD word timestamps into a jump-cut short's new (shorter) timeline.

Reads the full VOD's word-level transcript, keeps only words that fall
inside the given kept segments, and rewrites each word's start/end as its
position in the concatenated jump-cut output instead of the raw VOD.

Usage: remap_words_jumpcut.py <segments.json> <full_vod_words.json> <out_words.json>
"""
import json
import sys


def main():
    seg_path, words_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    segments = json.load(open(seg_path, encoding="utf-8"))
    full = json.load(open(words_path, encoding="utf-8"))

    cumulative = 0.0
    out_words = []
    for seg in segments:
        s, e = seg["start"], seg["end"]
        for fseg in full["segments"]:
            for w in fseg.get("words", []):
                if "start" not in w or "end" not in w:
                    continue
                # keep a word only if it falls fully inside this kept segment
                if w["start"] >= s and w["end"] <= e:
                    out_words.append({
                        "start": cumulative + (w["start"] - s),
                        "end": cumulative + (w["end"] - s),
                        "word": w.get("word", ""),
                    })
        cumulative += e - s

    out_words.sort(key=lambda w: w["start"])
    out = {"segments": [{"words": out_words}]}
    json.dump(out, open(out_path, "w", encoding="utf-8"), indent=2)
    print(f"remapped {len(out_words)} words, new timeline length {cumulative:.1f}s")


if __name__ == "__main__":
    main()
