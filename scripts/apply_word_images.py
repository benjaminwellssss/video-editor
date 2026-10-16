"""Give every caption card whose word is in assets/word_images.json that word's image, as a card note.

Usage: python apply_word_images.py <captions.json> [<captions.json> ...]

A word used several times in one video gets the next image in its list each time. The starting image depends on
the clip folder's name, so different videos don't all open on the same one. Cards that already have a note are left
alone, because hand edits win. Run it after building cards and before editing; the editor shows the notes, so any of
them can be changed or deleted there. render_captions.py downloads linked images (or reads files under assets/).
"""
import hashlib
import json
import os
import re
import sys

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "word_images.json")


def load_rules():
    raw = {k: v for k, v in json.load(open(RULES, encoding="utf-8")).items() if not k.startswith("_")}
    return {k: raw[v] if isinstance(v, str) else v for k, v in raw.items()}  # "parried": "parry" shares parry's list


def apply(cards, rules, seed):
    used = {}
    for card in cards:
        word = re.sub(r"[^a-z']", "", " ".join(card.get("lines", [])).lower())
        if word not in rules or card.get("note"):
            continue
        imgs = rules[word]
        key = id(imgs)  # aliases share a counter with the word they point to
        start = int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(imgs)
        card["note"] = imgs[(start + used.get(key, 0)) % len(imgs)]
        used[key] = used.get(key, 0) + 1
    return sum(used.values())


if __name__ == "__main__":
    rules = load_rules()
    # self-check: repeats rotate, existing notes are kept
    demo = [{"lines": ["PARRY"]}, {"lines": ["PARRIED"]}, {"lines": ["PARRY"], "note": "keep"}]
    assert apply(demo, rules, "x") == 2 and demo[0]["note"] != demo[1]["note"] and demo[2]["note"] == "keep"
    for path in sys.argv[1:]:
        cards = json.load(open(path, encoding="utf-8"))
        n = apply(cards, rules, os.path.basename(os.path.dirname(os.path.abspath(path))))
        json.dump(cards, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print(f"{path}: {n} word images")
