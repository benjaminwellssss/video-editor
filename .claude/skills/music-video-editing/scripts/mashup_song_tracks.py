"""Per-song source position across a mashup, for side-by-side panels.

Unlike mashup_segments.py (one visual owner at a time), every song gets its own
continuous track: for each window, take that song's matches from the vocal, other
and bass stems, follow the chain the song is already on when a match agrees with
it, jump to a new position only on a confident match, and otherwise keep playing
forward. Short-lived jumps are folded back into the surrounding chain.

Each jump is then placed on the exact beat: between the last window that backed
the old chain and the first that backed the new one, every beat is tested by
correlating the song's stems against both alignments, and the cut goes on the
first beat where the new alignment wins.

usage: mashup_song_tracks.py <source_map_raw.json> <mashup_bpm> <grid0> <end_s> <out.json>
                             <mashup_stems_dir> NAME=BPM=STEMS_DIR=SEMITONES ...
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from match_mashup_sources import DT, feats, stretch  # noqa: E402

STEP_TOL = 0.6    # seconds of slack for "agrees with the current chain"
JUMP_SCORE = 0.6  # a disagreeing match must be this confident to start a new chain
MIN_DB = -40
MIN_WINDOWS = 3   # chains shorter than this get folded into their neighbours


def zn(w):
    w = w - w.mean(axis=1, keepdims=True)
    return w / (np.linalg.norm(w) + 1e-9)


def align_score(mf, sf, t, off, ratio, semi, length):
    """How well the mashup at [t, t+length] matches the song placed at offset `off`."""
    i, n = int(t / DT), int(length / DT)
    j = int((off + t * ratio) / ratio / DT)  # source seconds -> stretched-song frame
    total = 0.0
    for stem, (f, rms) in mf.items():
        if j < 0 or j + n > sf[stem].shape[1] or 20 * np.log10(rms[i:i + n].mean() + 1e-9) < MIN_DB:
            continue
        total += float((zn(f[:, i:i + n]) * zn(np.roll(sf[stem][:, j:j + n], semi, axis=0))).sum())
    return total


def main():
    rows = json.load(open(sys.argv[1]))
    mbpm, grid0, end_s, out, mdir = (float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]),
                                     sys.argv[5], sys.argv[6])
    songs = {}
    for a in sys.argv[7:]:
        name, bpm, d, semi = a.split("=")
        songs[name] = (mbpm / float(bpm), float(bpm), d, int(semi))
    beat = 60 / mbpm
    snap = lambda t: grid0 + round((t - grid0) / beat) * beat
    stems = ["vocals", "other", "bass"]
    mf = {s: feats(f"{mdir}/{s}.wav", s) for s in stems}
    result = {}

    for name, (ratio, bpm, sdir, semi) in songs.items():
        chains = []  # each: {"off": src - t*ratio, "pts": [t...], "ev": [t with evidence]}
        for r in rows:
            cands = []
            for stem in stems:
                e = r["stems"][stem]
                m = e["match"].get(name)
                if m and e["db"] > MIN_DB:
                    cands.append((m["score"], m["src_t"] - r["t"] * ratio))
            cur = chains[-1] if chains else None
            agree = [c for c in cands if cur and abs(c[1] - cur["off"]) < STEP_TOL]
            strong = [c for c in cands if c[0] >= JUMP_SCORE]
            if agree:
                cur["pts"].append(r["t"])
                cur["ev"].append(r["t"])
            elif strong:
                chains.append({"off": max(strong)[1], "pts": [r["t"]], "ev": [r["t"]]})
            elif cur:
                cur["pts"].append(r["t"])  # no evidence: keep playing forward
            else:
                chains.append({"off": max(cands)[1] if cands else -r["t"] * ratio, "pts": [r["t"]], "ev": []})

        # fold short chains: same offset as a neighbour -> merge, else absorb into previous
        changed = True
        while changed:
            changed = False
            for i, c in enumerate(chains):
                if len(c["ev"]) >= MIN_WINDOWS or len(chains) == 1:
                    continue
                prev = chains[i - 1] if i > 0 else None
                nxt = chains[i + 1] if i + 1 < len(chains) else None
                if prev and nxt and abs(prev["off"] - nxt["off"]) < STEP_TOL:
                    prev["pts"] += c["pts"] + nxt["pts"]
                    prev["ev"] += nxt["ev"]
                    del chains[i:i + 2]
                elif prev:
                    prev["pts"] += c["pts"]
                    del chains[i]
                else:
                    nxt["pts"] = c["pts"] + nxt["pts"]
                    del chains[i]
                changed = True
                break

        # refine each jump to the beat where the new alignment starts winning
        sf = {s: stretch(feats(f"{sdir}/{s}.wav", s)[0], bpm / mbpm) for s in stems}
        bar = 4 * beat
        cuts = []
        for a, b in zip(chains, chains[1:]):
            lo = snap(a["ev"][-1] + bar / 2) if a["ev"] else snap(a["pts"][0])
            hi = snap(b["ev"][0] + bar / 2)
            cut = hi
            t = lo
            while t <= hi + 1e-6:
                if align_score(mf, sf, t, b["off"], ratio, semi, bar) > align_score(mf, sf, t, a["off"], ratio, semi, bar):
                    cut = t
                    break
                t += beat
            cuts.append(round(cut, 3))

        segs = []
        bounds = [grid0] + cuts + [end_s]
        for c, start, end in zip(chains, bounds, bounds[1:]):
            src = c["off"] + start * ratio
            if src < 0:  # song hasn't started yet: the clip starts where the source does
                start = round(-c["off"] / ratio, 3)
                src = 0.0
            segs.append({"start": start, "end": end, "src_at_start": round(src, 3),
                         "src_offset": round(c["off"], 4), "evidence": len(c["ev"])})
        result[name] = segs
        print(name)
        for s in segs:
            print(f"  {s['start'] - grid0:7.2f}-{s['end'] - grid0:7.2f}  src {s['src_at_start']:7.2f}  ({s['evidence']} matched)")
    json.dump(result, open(out, "w"), indent=1)


if __name__ == "__main__":
    main()
