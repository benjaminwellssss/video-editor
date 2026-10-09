"""Sanity-check caption cards against the actual voice audio, so a mistimed or
phantom caption is caught before it's rendered.

Why this exists: a caption set can look right on paper and still be wrong.
Word aligners stretch a word across the silence before it, drop words at a
clip's edges (a clip-only transcript has no surrounding audio to work with),
and Whisper invents short words like "you" in silence. Comparing against
an *isolated voice* track (no game/music) exposes all of those.

Usage: python verify_caption_timing.py <cards.json> <voice.wav> [<fps> <a:b> <a:b> ...]

<voice.wav> must be on the same timeline as the cards. If it's the *uncut*
voice for a short that was re-cut by hand, pass the kept source-frame ranges
(same as build_cards_from_ranges.py) and the audio is cut to match first.

Reports three things: PHANTOM (a card on screen while there is no voice at
all - an invented or badly misplaced word), EARLY (a card up far longer than
the normal ~0.12s lead before any voice - a word stretched across the
silence before it), and UNCAPTIONED (speech with no caption at all - a
dropped word). Judged on the whole span the card is visible, not a guess at
the word's exact edges, so short unstressed words don't false-alarm.
"""
import json
import sys
import wave

import numpy as np


def load_wav(path):
    w = wave.open(path)
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    if w.getnchannels() > 1:
        x = x.reshape(-1, w.getnchannels()).mean(axis=1)
    return x, w.getframerate()


def main():
    cards = json.load(open(sys.argv[1], encoding="utf-8"))
    x, sr = load_wav(sys.argv[2])
    if len(sys.argv) > 3:
        fps = float(sys.argv[3])
        x = np.concatenate([x[int(a / fps * sr):int(b / fps * sr)]
                            for a, b in (tuple(int(v) for v in r.split(":")) for r in sys.argv[4:])])

    hop = sr // 100  # 10 ms
    env = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2)) for i in range(0, len(x) - hop, hop)])
    speech = float(np.median(env[env > np.percentile(env, 60)]))
    lvl = lambda a, b: float(np.mean(env[int(a * 100):max(int(b * 100), int(a * 100) + 1)])) / speech
    print(f"voice: {len(env) / 100:.1f}s, typical speech level {speech:.4f}; cards: {len(cards)}")

    problems = 0
    for c in cards:
        text = " ".join(c["lines"])
        seg = env[int(c["start"] * 100):max(int(c["end"] * 100), int(c["start"] * 100) + 1)] / speech
        if seg.size == 0:
            continue
        if seg.max() < 0.30:
            problems += 1
            print(f"  PHANTOM '{text}' {c['start']:.2f}-{c['end']:.2f}: no voice at all while this card is "
                  f"on screen (peak {seg.max():.2f}x) - invented word or badly misplaced")
            continue
        # cards start on the word itself (LEAD_S = 0), so a normal card hears its
        # voice within ~0.1s; much longer means it is up early - typically a word
        # stretched across the silence before it
        voiced_at = np.argmax(seg > 0.15) / 100
        if voiced_at > 0.25:
            problems += 1
            print(f"  EARLY  '{text}' {c['start']:.2f}-{c['end']:.2f}: card is up {voiced_at:.2f}s before "
                  f"any voice (expected ~0s)")
        elif c["end"] - c["start"] > 1.0 and len(c["lines"]) == 1 and " " not in c["lines"][0]:
            problems += 1
            print(f"  LONG   '{text}' {c['start']:.2f}-{c['end']:.2f}: one word held {c['end'] - c['start']:.2f}s "
                  f"- likely swallowed neighbouring words that were never transcribed")
    voiced = env / speech > 0.15
    i = 0
    while i < len(voiced):
        if voiced[i]:
            j = i
            while j < len(voiced) and (voiced[j] or voiced[j:j + 4].any()):
                j += 1
            a, b = i / 100, j / 100
            if b - a >= 0.25 and not any(c["start"] + 0.12 < b and c["end"] > a for c in cards):
                problems += 1
                print(f"  UNCAPTIONED speech {a:.2f}-{b:.2f}s ({b - a:.2f}s of voice with no caption)")
            i = j
        i += 1
    print("OK: every caption sits on speech and all speech is captioned" if not problems
          else f"{problems} problem(s) above - check them before rendering")


if __name__ == "__main__":
    main()
