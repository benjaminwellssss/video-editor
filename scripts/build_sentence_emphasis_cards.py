"""Build caption cards for a jump-cut short, same as build_short_cards_from_segments.py,
but the LAST WORD OF EVERY SENTENCE always gets its own standalone card (never
the tail of a longer multi-word card) and is flagged "emphasis_scale" for a
larger on-screen render. Sentence boundaries come from terminal punctuation
(. ? !) on the raw (pre-clean_word) transcript word.

Usage: <venv-python> build_sentence_emphasis_cards.py <segments.json> <full_words.json> <out_cards.json> [emphasis_scale]

Optional inline text substitutions specific to one short (not the shared,
global EMOJI_SUBS in build_caption_cards.py — those are for censoring, not
one-off jokes) go in WORD_SUBS below, keyed on the cleaned (uppercased,
punctuation-stripped) word.
"""
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from build_caption_cards import clean_word

LEAD_S = 0.0  # cards start on the word (see build_caption_cards.py)

WORD_SUBS = {
    "BITTER": "\U0001F171️ETER",  # 🅱️ETER
    "MOSQUITOES": "MOSKEETERS",
}


def sub_word(clean):
    return WORD_SUBS.get(clean, clean)


def raw_group(words):
    """Same grouping as build_caption_cards.words_to_cards, but also forces a
    break right after any sentence-final word, and returns cards WITHOUT the
    trailing lead-adjustment pass (done once, globally, by the caller)."""
    cards = []
    i = 0
    n = len(words)
    while i < n:
        group = [words[i]]
        i += 1
        while i < n and len(group) < 4:
            if group[-1]["sentence_final"]:
                break
            gap = words[i]["start"] - group[-1]["end"]
            if gap > 0.6:
                break
            group.append(words[i])
            i += 1

        lines = [" ".join(w["text"] for w in group[:2])]
        if len(group) > 2:
            lines.append(" ".join(w["text"] for w in group[2:4]))

        start = group[0]["start"]
        end = group[-1]["end"] + 0.12
        if i < n:
            end = min(end, words[i]["start"])
        end = max(end, start + 0.15)

        word_timing = [{"text": w["text"], "start": w["start"], "end": w["end"],
                         "line": 0 if wi < 2 else 1} for wi, w in enumerate(group)]
        cards.append({"start": start, "end": end, "lines": lines, "words": word_timing,
                       "_sentence_final_tail": group[-1]["sentence_final"]})
    return cards


def split_sentence_final_tail(cards, emphasis_scale):
    out = []
    for card in cards:
        words = card["words"]
        if card["_sentence_final_tail"] and len(words) > 1:
            *lead, last = words
            lead_lines = [" ".join(w["text"] for w in lead[:2])]
            if len(lead) > 2:
                lead_lines.append(" ".join(w["text"] for w in lead[2:4]))
            lead_end = min(lead[-1]["end"] + 0.12, last["start"])
            out.append({"start": card["start"], "end": max(lead_end, lead[0]["start"] + 0.15),
                        "lines": lead_lines, "words": lead})
            last_solo = {**last, "line": 0}
            out.append({"start": last["start"], "end": card["end"], "lines": [last["text"]],
                        "words": [last_solo], "emphasis_scale": emphasis_scale})
        else:
            was_sentence_final = card.pop("_sentence_final_tail")
            if was_sentence_final:
                card["emphasis_scale"] = emphasis_scale
            out.append(card)
    return out


def main():
    seg_path, words_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    emphasis_scale = float(sys.argv[4]) if len(sys.argv) > 4 else 1.1

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
                raw_text = w.get("word", "")
                clean = clean_word(raw_text)
                if not clean:
                    continue
                clean = sub_word(clean)
                mapped.append({
                    "start": offset + (w["start"] - a),
                    "end": offset + (w["end"] - a),
                    "text": clean,
                    "sentence_final": bool(re.search(r"[.?!]\s*$", raw_text.strip())),
                })
        offset += b - a

    cards = raw_group(mapped)
    cards = split_sentence_final_tail(cards, emphasis_scale)

    for idx, card in enumerate(cards):
        new_start = card["start"] - LEAD_S
        if idx > 0:
            new_start = max(new_start, cards[idx - 1]["end"])
        card["start"] = max(0.0, new_start)

    json.dump(cards, open(out_path, "w", encoding="utf-8"), indent=2)
    total_dur = cards[-1]["end"] if cards else 0
    n_emphasis = sum(1 for c in cards if c.get("emphasis_scale"))
    print(f"{len(cards)} cards ({n_emphasis} sentence-final/emphasized) from {len(mapped)} "
          f"mapped words, last card ends {total_dur:.1f}s")


if __name__ == "__main__":
    main()
