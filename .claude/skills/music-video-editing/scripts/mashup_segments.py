"""Turn match_mashup_sources.py windows into a visual segment list.

Each window gets one "visual owner": the song whose vocals are singing (so the
singer can lip-sync), else the song owning the instrumental (other+bass). Runs of
windows from the same song whose source position advances at the expected rate
become one segment; each segment's source offset is a least-squares fit over its
windows, so one bad window doesn't shift the whole segment.

usage: mashup_segments.py <source_map_raw.json> <mashup_bpm> <out.json> NAME=BPM ...
"""
import json
import sys

import numpy as np

VOCAL_DB = -32     # vocal stem quieter than this = nobody singing
MIN_SCORE = 0.45   # weaker vocal matches are treated as no match
STEP_TOL = 0.6     # seconds of slack when chaining windows
GRID0 = 3.753      # bar 1 downbeat in the recording (from the drum stem); cuts snap to beats


def owner(row):
    v = row["stems"]["vocals"]
    if v["db"] > VOCAL_DB and v["match"]:
        name = max(v["match"], key=lambda k: v["match"][k]["score"])
        m = v["match"][name]
        if m["score"] >= MIN_SCORE:
            return name, m["src_t"], "vocals"
    # instrumental: whichever song other+bass agree on best
    best = None
    for s in ["other", "bass"]:
        e = row["stems"][s]
        for name, m in e["match"].items():
            if e["db"] > -40 and (best is None or m["score"] > best[2]):
                best = (name, m["src_t"], m["score"])
    return (best[0], best[1], "inst") if best else (None, None, "silent")


def main():
    rows = json.load(open(sys.argv[1]))
    mbpm, out = float(sys.argv[2]), sys.argv[3]
    ratio = {a.split("=")[0]: mbpm / float(a.split("=")[1]) for a in sys.argv[4:]}
    hop = rows[1]["t"] - rows[0]["t"]

    segs = []
    for r in rows:
        name, src, kind = owner(r)
        if name is None:
            continue
        cur = segs[-1] if segs else None
        if cur and cur["song"] == name:
            expect = cur["pts"][-1][1] + (r["t"] - cur["pts"][-1][0]) * ratio[name]
            if abs(src - expect) < STEP_TOL:
                cur["pts"].append((r["t"], src))
                cur["kinds"].add(kind)
                continue
            if r["t"] - cur["pts"][-1][0] <= hop + 1e-6 and kind == "inst":
                # stray instrumental window that doesn't chain: keep extending
                cur["pts"].append((r["t"], expect))
                continue
        segs.append({"song": name, "pts": [(r["t"], src)], "kinds": {kind}})

    def offset(s):
        # fixed slope = tempo ratio; fit only the offset
        return float(np.median([src - t * ratio[s["song"]] for t, src in s["pts"]]))

    # Smooth: a lone window between two compatible pieces of one chain is a
    # mis-match inside that chain; any other lone window joins its predecessor.
    changed = True
    while changed:
        changed = False
        for i in range(1, len(segs) - 1):
            a, b, c = segs[i - 1], segs[i], segs[i + 1]
            if len(b["pts"]) == 1 and a["song"] == c["song"] and abs(offset(a) - offset(c)) < STEP_TOL:
                a["pts"] += c["pts"]
                a["kinds"] |= c["kinds"]
                del segs[i:i + 2]
                changed = True
                break
        if not changed:
            for i in range(1, len(segs)):
                if len(segs[i]["pts"]) == 1:
                    prev = segs[i - 1]
                    t = segs[i]["pts"][0][0]
                    prev["pts"].append((t, offset(prev) + t * ratio[prev["song"]]))
                    del segs[i]
                    changed = True
                    break

    grid0, beat = GRID0, 60 / mbpm
    snap = lambda t: round(grid0 + round((t - grid0) / beat) * beat, 3)
    result = []
    for s in segs:
        t = np.array([p[0] for p in s["pts"]])
        off = offset(s)
        start, end = snap(t[0]), snap(t[-1] + hop)
        if result:
            start = result[-1]["end"]  # butt-join, no gaps
        result.append({
            "song": s["song"],
            "start": start,
            "end": end,
            "src_at_start": round(off + start * ratio[s["song"]], 3),
            "src_offset": round(off, 4),
            "kind": "vocals" if "vocals" in s["kinds"] else "inst",
            "windows": len(t),
        })
    json.dump(result, open(out, "w"), indent=1)
    for s in result:
        print(f"{s['start']:7.2f}-{s['end']:7.2f}  {s['song']:4} {s['kind']:6} src {s['src_at_start']:7.2f}  ({s['windows']} win)")


if __name__ == "__main__":
    main()
