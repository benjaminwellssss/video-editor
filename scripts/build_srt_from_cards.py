"""Build an SRT from single-word caption cards.json (as built by
build_short_cards_from_segments.py ... single), by regrouping words into
normal-sized subtitle chunks. Useful as a plain-text/reference export
alongside the cards.json a short's captions are actually edited from.

Usage: python build_srt_from_cards.py <cards.json> <out.srt>
"""
import json
import sys

MAX_CHUNK_WORDS = 10
MAX_CHUNK_SECONDS = 4.0
GAP_BREAK_SECONDS = 1.0
MIN_WORDS_FOR_SENTENCE_BREAK = 4


def tc(t):
    ms = round(max(t, 0) * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    cards_path, out_path = sys.argv[1], sys.argv[2]
    cards = json.load(open(cards_path, encoding="utf-8"))
    chunks, cur = [], []

    def flush():
        if cur:
            chunks.append((cur[0][0], cur[-1][1], " ".join(t for _, _, t in cur)))
            cur.clear()

    for c in cards:
        text = " ".join(c.get("lines", [])).strip()
        if not text:
            continue
        s, e = c["start"], c["end"]
        if cur and (s - cur[-1][1] > GAP_BREAK_SECONDS or e - cur[0][0] > MAX_CHUNK_SECONDS
                    or len(cur) >= MAX_CHUNK_WORDS):
            flush()
        cur.append((s, e, text))
        if text[-1] in ".?!" and len(cur) >= MIN_WORDS_FOR_SENTENCE_BREAK:
            flush()
    flush()

    with open(out_path, "w", encoding="utf-8") as f:
        for i, (s, e, text) in enumerate(chunks, 1):
            nxt = chunks[i][0] if i < len(chunks) else None
            e = min(e + 0.15, nxt - 0.02) if nxt is not None else e + 0.15
            e = max(e, s + 0.2)
            f.write(f"{i}\n{tc(s)} --> {tc(e)}\n{text}\n\n")
    print(f"{len(chunks)} subtitles -> {out_path}")


if __name__ == "__main__":
    main()
