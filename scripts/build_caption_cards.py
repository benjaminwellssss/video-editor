"""Group a single-track word transcript into pop-in caption cards.

Up to 4 words per card, split 2 words per line (top line / bottom line).
A card breaks early on a >0.6s gap between words (natural pause).

Usage: <venv-python> build_caption_cards.py <name> <out_cards.json> [shorts_dir]
"""
import json
import re
import sys

SHORTS_DIR = r"E:\video-editor-projects\valheimin-ep1-longplay-vod\shorts"
LEAD_S = 0.12  # pull each card's start slightly earlier so it never lags the word

# on-screen caption text only — does not affect whether the word is censored
# in audio (see skill's Censoring tiers: "ass"/"shit" keep their audio, only
# "fuck"/slurs get cut). Exact whole-word match only, not substring (so
# "GLASS"/"PASSING" are untouched).
EMOJI_SUBS = {
    "ASS": "\U0001F434",       # 🐴 donkey
    "FUCK": "\U0001F92D\U0001F92D\U0001F92D",
    "SHIT": "\U0001F4A9",      # 💩
    "FAGGOT": "\u26A0\uFE0F\u26A0\uFE0F\u26A0\uFE0F",
}


def clean_word(w):
    cleaned = re.sub(r"[^A-Za-z0-9'\-]", "", w).upper()
    if cleaned in EMOJI_SUBS:
        return EMOJI_SUBS[cleaned]
    # hyphenated compounds (e.g. "KISS-ASS") — substitute the matching part and
    # drop the hyphen against an emoji (want "KISS🐴", not "KISS-🐴"): a
    # hyphen is a word-joining mark for two text words, not for text-next-to-
    # a-pictograph, where it just reads as a stray dash floating in a gap.
    if "-" in cleaned:
        parts = cleaned.split("-")
        if any(p in EMOJI_SUBS for p in parts):
            out = ""
            for idx, p in enumerate(parts):
                sub = EMOJI_SUBS.get(p, p)
                if idx > 0:
                    prev_was_emoji = parts[idx - 1] in EMOJI_SUBS
                    this_is_emoji = p in EMOJI_SUBS
                    if not (prev_was_emoji or this_is_emoji):
                        out += "-"
                out += sub
            return out
    return cleaned


def load_words(path):
    d = json.load(open(path, encoding="utf-8"))
    words = []
    for seg in d["segments"]:
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            clean = clean_word(w.get("word", ""))
            if not clean:
                continue
            words.append({"start": w["start"], "end": w["end"], "text": clean})
    return words


def words_to_cards(words):
    cards = []
    i = 0
    n = len(words)
    while i < n:
        group = [words[i]]
        i += 1
        while i < n and len(group) < 4:
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

        # per-word timing + line index, for the karaoke-style active-word
        # highlight — kept separate from "lines" (which stays plain joined
        # text for anything that doesn't need per-word granularity).
        word_timing = []
        for wi, w in enumerate(group):
            word_timing.append({
                "text": w["text"],
                "start": w["start"],
                "end": w["end"],
                "line": 0 if wi < 2 else 1,
            })

        cards.append({"start": start, "end": end, "lines": lines, "words": word_timing})

    # apply a small early lead to each card's start so captions never lag the
    # audio; never overlap the previous card's end while doing so.
    for idx, card in enumerate(cards):
        new_start = card["start"] - LEAD_S
        if idx > 0:
            new_start = max(new_start, cards[idx - 1]["end"])
        card["start"] = max(0.0, new_start)

    return cards


def words_to_cards_single(words):
    """One word per card, shown exactly while it's being spoken (plus the
    same small early LEAD_S already used for the grouped style). No 'words'
    key — that key only exists to drive the karaoke active-word highlight,
    which is meaningless when the whole card is already one word; omitting
    it keeps render_captions.py's plain-white path (no green tint)."""
    cards = []
    n = len(words)
    for i, w in enumerate(words):
        start = w["start"]
        end = w["end"] + 0.12
        if i + 1 < n:
            end = min(end, words[i + 1]["start"])
        end = max(end, start + 0.15)
        cards.append({"start": start, "end": end, "lines": [w["text"]]})

    for idx, card in enumerate(cards):
        new_start = card["start"] - LEAD_S
        if idx > 0:
            new_start = max(new_start, cards[idx - 1]["end"])
        card["start"] = max(0.0, new_start)

    return cards


def main():
    name, out_path = sys.argv[1], sys.argv[2]
    shorts_dir = sys.argv[3] if len(sys.argv) > 3 else SHORTS_DIR
    words = load_words(f"{shorts_dir}\\{name}_track0_words.json")
    cards = words_to_cards(words)
    json.dump(cards, open(out_path, "w", encoding="utf-8"), indent=2)
    total_dur = cards[-1]["end"] if cards else 0
    print(f"{name}: {len(cards)} cards, last card ends {total_dur:.1f}s")


if __name__ == "__main__":
    main()
