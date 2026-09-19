"""Build single-word, speaker-colored caption cards for a short that was
re-cut by hand in Resolve, so captions follow the edit instead of the
original base video's timing.

Takes a diarized transcript (transcribe_diarized.py output, timed against
the *base* clip the Resolve timeline was built from) plus the kept source
ranges from Resolve's source_range_report, drops every word that falls in a
removed stretch, and shifts the rest onto the edited timeline.

Usage: python build_cards_from_ranges.py <diarized.json> <out_cards.json> <fps> <start:end> [<start:end> ...]

Ranges are source FRAMES at <fps> (end exclusive), in timeline order, exactly
as Resolve reports them, e.g. `30 0:1175 1248:1330 1406:1708`.

Color: the speaker with the most words-time is Ben (green); others get
yellow/red/blue by first appearance (same rule as build_speaker_colors.py,
including its caveat: heuristic per short, spot-check close races).
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from build_caption_cards import clean_word, words_to_cards_single
from build_speaker_colors import GREEN, OTHER_COLORS


def load_words(path):
    data = json.load(open(path, encoding="utf-8"))
    words, last_speaker = [], None
    for seg in data["segments"]:
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            speaker = w.get("speaker") or last_speaker
            last_speaker = speaker
            words.append({"raw": w.get("word", ""), "start": w["start"], "end": w["end"], "speaker": speaker})
    words.sort(key=lambda w: w["start"])
    return words


def main():
    diarized_path, out_path, fps = sys.argv[1], sys.argv[2], float(sys.argv[3])
    ranges = [tuple(int(x) for x in a.split(":")) for a in sys.argv[4:]]

    words = load_words(diarized_path)
    mapped, offset = [], 0.0
    for a_fr, b_fr in ranges:
        a, b = a_fr / fps, b_fr / fps
        for w in words:
            if w["start"] >= a and w["end"] <= b:
                text = clean_word(w["raw"])
                if text:
                    mapped.append({
                        "start": offset + (w["start"] - a),
                        "end": offset + (w["end"] - a),
                        "text": text,
                        "speaker": w["speaker"],
                    })
        offset += b - a

    cards = words_to_cards_single([{"start": m["start"], "end": m["end"], "text": m["text"]} for m in mapped])
    assert len(cards) == len(mapped), "words_to_cards_single is expected to emit one card per word"

    totals, first_seen = {}, {}
    for m in mapped:
        sp = m["speaker"]
        if sp is None:
            continue
        totals[sp] = totals.get(sp, 0.0) + (m["end"] - m["start"])
        first_seen.setdefault(sp, m["start"])
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    color_map = {}
    if ranked:
        color_map[ranked[0][0]] = GREEN
        others = sorted((sp for sp in totals if sp != ranked[0][0]), key=lambda sp: first_seen[sp])
        for i, sp in enumerate(others):
            color_map[sp] = OTHER_COLORS[i % len(OTHER_COLORS)]

    for card, m in zip(cards, mapped):
        if m["speaker"] in color_map:
            card["fill"] = color_map[m["speaker"]]

    json.dump(cards, open(out_path, "w", encoding="utf-8"), indent=2)
    print(f"{len(cards)} cards from {len(words)} transcript words ({len(words) - len(mapped)} dropped: inside cuts or empty), "
          f"edited length {offset:.3f}s")
    print(f"speaker totals (s): { {sp: round(d, 1) for sp, d in ranked} }; heaviest -> green")
    if len(ranked) > 1 and ranked[1][1] > 0 and ranked[0][1] / ranked[1][1] < 1.3:
        print("  <-- close race between top two speakers, spot-check colors")


if __name__ == "__main__":
    main()
