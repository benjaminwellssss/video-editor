#!/usr/bin/env python3
"""Family-name protection: the user's family names never reach a caption, SRT or the audio.

The patterns live in assets/protected_names.json, which is git-ignored on purpose so the
names never become public. Transcribe scripts call scrub() before writing words.json, so
every downstream text (captions, SRTs, metadata drafts) only ever sees MARK; the cut
builders (build_vod_cut.py, prep_shorts_batch.py) excise those words from the audio.

Usage (existing transcripts): python scripts/protected_names.py <words.json> [...] [--check]
  scrubs each file in place and prints the hit count; --check only reports.
"""
import json
import re
import sys
from pathlib import Path

LIST = Path(__file__).resolve().parent.parent / "assets" / "protected_names.json"
MARK = "\U0001F910"  # 🤐


def _load():
    if not LIST.exists():
        print(f"WARNING: {LIST} is missing; family names are NOT being protected", file=sys.stderr)
        return None
    return re.compile(r"^(?:%s)$" % "|".join(json.load(open(LIST, encoding="utf8"))["patterns"]), re.I)


_RE = _load()


def _norm(tok):
    t = re.sub(r"[^a-z']", "", tok.lower().replace("’", "'"))
    return re.sub(r"'s?$", "", t).replace("'", "")


def is_protected(tok):
    return bool(_RE and tok and _RE.match(_norm(tok)))


def is_cut(w):
    """A transcript word whose audio must be excised."""
    return bool(w.get("protected")) or MARK in w.get("word", "") or is_protected(w.get("word", ""))


def scrub_text(text):
    return re.sub(r"[A-Za-z'’]+", lambda m: MARK if is_protected(m.group()) else m.group(), text)


def scrub(obj):
    """Blank protected names in a WhisperX result / word list, in place. Returns the hit count."""
    hits = 0
    if isinstance(obj, list):
        return sum(scrub(x) for x in obj)
    if isinstance(obj, dict):
        if isinstance(obj.get("word"), str) and is_protected(obj["word"]):
            obj["word"], obj["protected"] = MARK, True
            hits += 1
        if isinstance(obj.get("text"), str):
            obj["text"] = scrub_text(obj["text"])
        hits += sum(scrub(v) for k, v in obj.items() if isinstance(v, (list, dict)))
    return hits


def carve(segs, words, pad=0.03, min_len=0.15):
    """Split [start, end] segments so every protected word's audio is cut out."""
    cuts = [(w["start"] - pad, w["end"] + pad) for w in words if "start" in w and "end" in w and is_cut(w)]
    out = []
    for s, e in segs:
        spans = [[s, e]]
        for cs, ce in cuts:
            nxt = []
            for a, b in spans:
                if ce <= a or cs >= b:
                    nxt.append([a, b])
                    continue
                if cs - a >= min_len:
                    nxt.append([a, round(cs, 3)])
                if b - ce >= min_len:
                    nxt.append([round(ce, 3), b])
            spans = nxt
        out.extend(spans)
    return out


if __name__ == "__main__":
    if _RE is None:
        sys.exit(1)
    check = "--check" in sys.argv
    for path in [a for a in sys.argv[1:] if a != "--check"]:
        data = json.load(open(path, encoding="utf8"))
        n = scrub(data)
        if n and not check:
            json.dump(data, open(path, "w", encoding="utf8"), ensure_ascii=False)
        print(f"{path}: {n} protected word(s){' (report only)' if check else ''}")
