"""Assign a per-speaker fill color to single-word caption cards, using
whisperx+pyannote diarization run separately on the short's own composited
audio (see transcribe_diarized.py, run against each short's _base.mp4).
Cards keep their existing start/end timing untouched — only a "fill" key
(see render_captions.py) is added per card.

Usage: python build_speaker_colors.py <cards.json> <diarized.json> <out_cards.json>

Color assignment: the diarized speaker with the most total speaking time in
this short is treated as Ben (green) — he's the streamer and the one who
marked the moment, so he's the majority speaker in most shorts, but not
guaranteed (e.g. a back-and-forth bit can be close to 50/50). Additional
speaker clusters get yellow/red/blue in order of first appearance. This is
a per-short heuristic, not a stable identity across shorts — diarization
labels aren't shared between independent runs, so "SPEAKER_00" in one short
has no relation to "SPEAKER_00" in another. The printed duration ratio
flags shorts worth a manual spot-check (close race = higher misattribution
risk).
"""
import json
import sys

GREEN = [140, 255, 120, 255]   # matches render_captions.HIGHLIGHT_GREEN
YELLOW = [255, 214, 0, 255]    # matches render_captions.YELLOW
RED = [255, 70, 70, 255]
BLUE = [90, 170, 255, 255]
OTHER_COLORS = [YELLOW, RED, BLUE]


def diarized_words(diarized):
    words = []
    for seg in diarized.get("segments", []):
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w or "speaker" not in w:
                continue
            words.append(w)
    words.sort(key=lambda w: w["start"])
    return words


def nearest_speaker(card_start, card_end, dwords):
    """Best time-overlap match; falls back to nearest-by-start-distance when
    the card falls in a diarization gap (no word overlaps it at all)."""
    best, best_overlap = None, -1.0
    for w in dwords:
        overlap = min(card_end, w["end"]) - max(card_start, w["start"])
        if overlap > best_overlap:
            best_overlap, best = overlap, w
    if best is not None and best_overlap > 0:
        return best["speaker"]
    if not dwords:
        return None
    return min(dwords, key=lambda w: abs(w["start"] - card_start))["speaker"]


def main():
    cards_path, diarized_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    cards = json.load(open(cards_path, encoding="utf-8"))
    diarized = json.load(open(diarized_path, encoding="utf-8"))
    dwords = diarized_words(diarized)

    totals, first_seen = {}, {}
    for w in dwords:
        sp = w["speaker"]
        totals[sp] = totals.get(sp, 0.0) + (w["end"] - w["start"])
        if sp not in first_seen:
            first_seen[sp] = w["start"]

    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    ben_speaker = ranked[0][0] if ranked else None
    others = sorted((sp for sp in totals if sp != ben_speaker), key=lambda sp: first_seen[sp])

    color_map = {}
    if ben_speaker is not None:
        color_map[ben_speaker] = GREEN
    for i, sp in enumerate(others):
        color_map[sp] = OTHER_COLORS[i % len(OTHER_COLORS)]

    for card in cards:
        speaker = nearest_speaker(card["start"], card["end"], dwords)
        if speaker in color_map:
            card["fill"] = color_map[speaker]

    json.dump(cards, open(out_path, "w", encoding="utf-8"), indent=2)

    print(f"speaker totals (s): { {sp: round(d, 1) for sp, d in ranked} }")
    print(f"ben = {ben_speaker} -> green; others -> {[(sp, color_map[sp]) for sp in others]}")
    if len(ranked) > 1 and ranked[1][1] > 0:
        ratio = ranked[0][1] / ranked[1][1]
        flag = "  <-- CLOSE RACE, spot-check this one" if ratio < 1.3 else ""
        print(f"top-two speaker duration ratio: {ratio:.2f}{flag}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
