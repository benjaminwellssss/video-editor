"""Build caption cards for a jump-cut short from a DIARIZED word transcript,
splitting into a "primary" row (always shows whoever is currently speaking)
and a "secondary" row (a second, smaller set of cards for a speaker talking
*over* whoever's already in the primary row — a genuine simultaneous
interjection, not just back-and-forth turn-taking).

Mapped through the short's own (start,end) segment list the same way
build_short_cards_from_segments.py does. Output shape:
  {"primary": [cards...], "secondary": [cards...]}
— feed straight to render_captions.py, which knows this dict shape.

Usage: <venv-python> build_speaker_cards.py <segments.json> <diarized_words.json> <out_cards.json>

diarized_words.json: WhisperX output after assign_word_speakers — each word
may carry a "speaker" key (e.g. "SPEAKER_00"); words WhisperX couldn't
confidently assign inherit the nearest earlier word's speaker.
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from build_caption_cards import clean_word

GAP_S = 0.6  # same "natural pause" threshold as build_caption_cards.words_to_cards


def load_all_words(full):
    words = []
    for seg in full["segments"]:
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            words.append(w)
    words.sort(key=lambda w: w["start"])
    # fill in missing speaker labels by carrying the previous word's speaker
    # forward (whisperx leaves a word unlabeled when no diarization turn
    # confidently covers it — usually a half-swallowed word at a turn boundary)
    last_speaker = None
    for w in words:
        spk = w.get("speaker")
        if spk is None:
            spk = last_speaker
        else:
            last_speaker = spk
        w["_speaker"] = spk
    return words


def map_words_through_segments(words, segments):
    """Same offset-remapping build_short_cards_from_segments.py does, but
    keeping the _speaker tag and returning a flat, time-sorted list."""
    mapped = []
    offset = 0.0
    for s in segments:
        a, b = s["start"], s["end"]
        for w in words:
            if w["start"] >= a and w["end"] <= b:
                clean = clean_word(w.get("word", ""))
                if not clean:
                    continue
                mapped.append({
                    "start": offset + (w["start"] - a),
                    "end": offset + (w["end"] - a),
                    "text": clean,
                    "speaker": w.get("_speaker") or "SPEAKER_00",
                })
        offset += b - a
    mapped.sort(key=lambda w: w["start"])
    return mapped


def words_to_speaker_cards(words):
    """Group a single speaker's own words into cards — identical grouping
    rule to build_caption_cards.words_to_cards (up to 4 words, 2 per line,
    break on >0.6s gap), just factored to run once per speaker."""
    cards = []
    i, n = 0, len(words)
    while i < n:
        group = [words[i]]
        i += 1
        while i < n and len(group) < 4:
            gap = words[i]["start"] - group[-1]["end"]
            if gap > GAP_S:
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
                       "speaker": group[0]["speaker"]})
    return cards


def split_card_at(card, t):
    """Split a card into (before, after) at time t — used when a secondary
    interjection outlasts the primary card it interrupted, so the tail
    becomes its own (promoted-to-primary) card instead of staying hidden in
    the secondary row after the primary card it overlapped has ended."""
    before_words = [w for w in card["words"] if w["start"] < t]
    after_words = [w for w in card["words"] if w["start"] >= t]
    if not before_words or not after_words:
        return card, None

    def rebuild(ws):
        lines = [" ".join(w["text"] for w in ws[:2])]
        if len(ws) > 2:
            lines.append(" ".join(w["text"] for w in ws[2:4]))
        relabeled = [{**w, "line": 0 if i < 2 else 1} for i, w in enumerate(ws)]
        return {"start": ws[0]["start"], "end": max(ws[-1]["end"] + 0.12, ws[0]["start"] + 0.15),
                "lines": lines, "words": relabeled, "speaker": card["speaker"]}

    return rebuild(before_words), rebuild(after_words)


def main():
    seg_path, words_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    segments = json.load(open(seg_path, encoding="utf-8"))
    full = json.load(open(words_path, encoding="utf-8"))

    all_words = load_all_words(full)
    mapped = map_words_through_segments(all_words, segments)

    by_speaker = {}
    for w in mapped:
        by_speaker.setdefault(w["speaker"], []).append(w)

    all_speaker_cards = []
    for spk, ws in by_speaker.items():
        all_speaker_cards.extend(words_to_speaker_cards(ws))
    all_speaker_cards.sort(key=lambda c: c["start"])

    primary, secondary = [], []
    for card in all_speaker_cards:
        if not primary or card["start"] >= primary[-1]["end"]:
            primary.append(card)
            continue
        # overlaps the current primary card — a simultaneous interjection.
        # if it runs past the primary card's end, split off the tail so
        # that trailing speech (now that the primary card is over) gets
        # promoted to its own primary card rather than staying hidden.
        overlap_end = primary[-1]["end"]
        head, tail = split_card_at(card, overlap_end)
        secondary.append(head)
        if tail is not None:
            primary.append(tail)

    primary.sort(key=lambda c: c["start"])
    secondary.sort(key=lambda c: c["start"])

    n_speakers = len(by_speaker)
    print(f"{len(mapped)} words, {n_speakers} speaker(s) detected: {list(by_speaker.keys())}")
    print(f"{len(primary)} primary cards, {len(secondary)} secondary (overlap) cards")

    json.dump({"primary": primary, "secondary": secondary}, open(out_path, "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()
