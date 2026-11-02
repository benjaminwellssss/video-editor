#!/usr/bin/env python3
"""Cover swears (fuck, shit, shite, ass, crap, bitch...) with the OSRS man-hit grunt, audio only.

Usage:
  censor_noise.py <in.mp4> <out.mp4> <plan.json> [<plan.json> ...]      long-form: build_vod_cut plans, in join order
  censor_noise.py --short <in.mp4> <out.mp4> <NN_name_cut.json>          short: cut json from build_shorts_*.py
Each later plan is offset by the duration of the plans before it. Video is stream-copied; the audio is re-encoded once.
"damn" and "hell" are left alone. Swears are never cut out any more: they get the grunt here and stars in captions.
"""
from local_paths import streaming
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_vod_cut as b  # noqa: E402

NOISE = streaming(r"Sound Effects\osrs_man_hit.wav")
PAD, GAIN = 0.03, 0.7


def hits_for(plan_path):
    plan = json.load(open(plan_path, encoding="utf8"))
    words = b.load_words(plan["words"])
    segs, total, _ = b.tighten(plan, words)
    pats = [re.compile(p, re.I) for p in plan.get("excise", b.DEFAULT_EXCISE)]
    tw = b.remap_words(segs, words, pats)
    return [(w["start"], w["end"], w["word"]) for w in tw if b.CENSOR_RE.match(b.clean(w["word"]))], total


def short_hits(cut_path):
    """Swears inside a shorts proof: cut json rows are [rec_frame, rec_end_frame, src_start_frame, part]."""
    cut = json.load(open(cut_path, encoding="utf8"))
    fps, hits, cache = cut["fps"], [], {}
    for rec, rec_end, src, part in cut["cut"]:
        if part not in cache:
            cache[part] = b.load_words(str(Path(cut_path).resolve().parent.parent / "transcript" / f"part{part}_words.json"))
        s0 = src / fps
        e0 = s0 + (rec_end - rec) / fps
        for w in cache[part]:
            if w["start"] >= s0 - 0.02 and w["end"] <= e0 + 0.02 and b.CENSOR_RE.match(b.clean(w["word"])):
                hits.append((rec / fps + w["start"] - s0, rec / fps + w["end"] - s0, w["word"]))
    return hits


STAR_RE = re.compile(r"^[A-Z]\*+[.,!?]*$")
EMOJI_CENSORED = {"💩", "🐴", "🤭🤭🤭"}  # build_caption_cards.EMOJI_SUBS (ass, shit, fuck)


def hits_from_cards(cards, facecam="Ben"):
    """Censored words in Cabtions cards (text starred like S**** or swapped for an emoji, see build_caption_cards.clean_word):
    returns (audio_hits, splat_hits), both [(start, end, word)]. The grunt covers every one; the hitsplat only the ones the
    person on the facecam says (card speaker missing = the facecam person, as in single-speaker clips)."""
    audio, splat = [], []
    for c in cards:
        words = c.get("words") or [{"text": t, "start": c["start"], "end": c["end"]} for ln in c["lines"] for t in ln.split()]
        for w in words:
            t = w["text"]
            if STAR_RE.match(t) or t in EMOJI_CENSORED:
                audio.append((w["start"], w["end"], t))
                if c.get("speaker") in (None, "", facecam):
                    splat.append((w["start"], w["end"], t))
    return audio, splat


def apply(src, dst, hits):
    for s, e, w in hits:
        print(f"{int(s // 60)}:{s % 60:05.2f}  {w}")
    if not hits:
        print("no swears: nothing to cover")
        return False
    mute = ",".join(f"volume=enable='between(t,{max(s - PAD, 0):.3f},{e + PAD:.3f})':volume=0" for s, e, _ in hits)
    fc = f"[0:a]{mute}[v];" + f"[1:a]asplit={len(hits)}" + "".join(f"[n{i}]" for i in range(len(hits))) + ";"
    fc += "".join(f"[n{i}]adelay={int(max(s - PAD, 0) * 1000)}|{int(max(s - PAD, 0) * 1000)},volume={GAIN}[d{i}];" for i, (s, _, _) in enumerate(hits))
    fc += "[v]" + "".join(f"[d{i}]" for i in range(len(hits))) + f"amix=inputs={len(hits) + 1}:normalize=0:duration=first,alimiter=limit=0.97:level=disabled[a]"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, "-i", NOISE, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)
    print(f"{len(hits)} words covered -> {dst}")
    return True


def main():
    args = sys.argv[1:]
    if args and args[0] == "--short":
        apply(args[1], args[2], short_hits(args[3]))
        return
    src, dst, plans = args[0], args[1], args[2:]
    hits, off = [], 0.0
    for p in plans:
        h, total = hits_for(p)
        hits += [(s + off, e + off, w) for s, e, w in h]
        off += total
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], text=True))
    assert abs(dur - off) < 6, f"plans total {off:.1f}s but video is {dur:.1f}s"  # LIVE card overlay keeps the length
    apply(src, dst, hits)


if __name__ == "__main__":
    main()
