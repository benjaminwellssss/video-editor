#!/usr/bin/env python3
"""Plan -> tightened segments -> SRT / metadata / Resolve clip_infos -> ffmpeg render.

A "VOD-style" long-form cut: chronological ranges of one source recording, dead
air between words trimmed, "fuck" variants excised at word level, and every
deliverable (SRT, metadata with chapters, flagged-word report, Resolve
clip_infos, finished MP4) derived from the same segment list.

Usage:
    python scripts/build_vod_cut.py <plan.json> [--no-render] [--only-render]

Plan JSON keys:
    name           file stem for outputs
    words          WhisperX words json ({"segments":[{"words":[...]}]} or a flat word list)
    source         source video
    audio_stream   0-based index among the source's audio streams (default 0)
    fps            source frame rate (default 30)
    out_dir        deliverable folder (mp4 / srt / metadata land here)
    job_dir        where <name>_cut.json / clip_infos / flagged report are written
    work_dir       scratch for per-segment encodes (deleted after a good render)
    title, description, tags, hashtags
    gap_min / gap_keep / lead / tail   dead-air tightening (defaults 3.0 / 1.0->lead+tail)
    excise         regexes of words to cut out (default: fuck variants)
    ranges         [[start_s, end_s, "chapter label (optional)"], ...]
"""
import json
import re
import subprocess
import sys
import concurrent.futures as cf
from pathlib import Path

FLAG_RE = re.compile(r"^(shit\w*|bullshit|ass|asses|bitch\w*|damn\w*|hell|pussy|tits?|crap|bastard\w*|dick\w*|piss\w*)$", re.I)
SLUR_RE = re.compile(r"^(retard\w*|fag\w*|nigg\w*|chink\w*|spic\w*|kike\w*|tranny\w*)$", re.I)
DEFAULT_EXCISE = [r"^f+u+c+k\w*$", r"^f\*+k\w*$"]


def load_words(path):
    d = json.load(open(path, encoding="utf8"))
    if isinstance(d, dict):
        d = [w for s in d["segments"] for w in s.get("words", [])]
    return sorted((w for w in d if "start" in w and "end" in w), key=lambda w: w["start"])


def clean(tok):
    return re.sub(r"[^A-Za-z*']", "", tok)


def tighten(plan, words):
    gap_min = plan.get("gap_min", 3.0)
    lead = plan.get("lead", 0.35)
    tail = plan.get("tail", 0.45)
    excise = [re.compile(p, re.I) for p in plan.get("excise", DEFAULT_EXCISE)]
    starts = [w["start"] for w in words]
    import bisect
    segs, excised = [], []
    for ri, rng in enumerate(plan["ranges"]):
        a, b = rng[0], rng[1]
        label = rng[2] if len(rng) > 2 else None
        lo = bisect.bisect_left(starts, a)
        hi = bisect.bisect_left(starts, b)
        ws = words[lo:hi]
        if not ws:
            segs.append({"start": a, "end": b, "label": label, "range": ri})
            continue
        cur_s = max(a - 0.2, ws[0]["start"] - lead)
        prev = ws[0]
        pieces = []
        for w in ws[1:]:
            if w["start"] - prev["end"] > gap_min:
                pieces.append((cur_s, prev["end"] + tail))
                cur_s = w["start"] - lead
            prev = w
        pieces.append((cur_s, min(b + 0.3, prev["end"] + tail)))
        # excise flagged words from every piece
        cuts = [(w["start"] - 0.03, w["end"] + 0.03, w) for w in ws if any(p.match(clean(w["word"])) for p in excise)]
        out = []
        for ps, pe in pieces:
            spans = [(ps, pe)]
            for cs, ce, w in cuts:
                nxt = []
                for s0, e0 in spans:
                    if ce <= s0 or cs >= e0:
                        nxt.append((s0, e0))
                        continue
                    excised.append(w)
                    if cs - s0 > 0.15:
                        nxt.append((s0, cs))
                    if e0 - ce > 0.15:
                        nxt.append((ce, e0))
                spans = nxt
            out.extend(spans)
        for i, (s0, e0) in enumerate(out):
            if e0 - s0 >= 0.4:
                segs.append({"start": round(s0, 3), "end": round(e0, 3), "label": label if i == 0 else None, "range": ri})
    # carry a chapter label forward if its first piece was dropped
    t = 0.0
    for sg in segs:
        sg["rec"] = round(t, 3)
        t += sg["end"] - sg["start"]
    return segs, t, {id(w): w for w in excised}.values()


def remap_words(segs, words, excise_pats):
    starts = [w["start"] for w in words]
    import bisect
    out = []
    for sg in segs:
        lo = bisect.bisect_left(starts, sg["start"])
        hi = bisect.bisect_left(starts, sg["end"])
        for w in words[lo:hi]:
            if any(p.match(clean(w["word"])) for p in excise_pats):
                continue
            ts = sg["rec"] + (w["start"] - sg["start"])
            te = sg["rec"] + (min(w["end"], sg["end"]) - sg["start"])
            out.append({"word": w["word"], "start": ts, "end": max(te, ts + 0.05)})
    return out


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(tw, total):
    cues, cur = [], []

    def flush():
        if not cur:
            return
        text = " ".join(w["word"] for w in cur).strip()
        if len(text) > 42:
            toks = text.split(" ")
            best, bi = 10**9, 1
            for i in range(1, len(toks)):
                d = abs(len(" ".join(toks[:i])) - len(" ".join(toks[i:])))
                if d < best:
                    best, bi = d, i
            text = " ".join(toks[:bi]) + "\n" + " ".join(toks[bi:])
        cues.append([cur[0]["start"], cur[-1]["end"] + 0.15, text])
        cur.clear()

    for w in tw:
        if cur:
            chars = len(" ".join(x["word"] for x in cur)) + len(w["word"]) + 1
            if (chars > 80 or w["end"] - cur[0]["start"] > 5.5 or w["start"] - cur[-1]["end"] > 0.9
                    or (cur[-1]["word"][-1:] in ".?!" and chars > 28)):
                flush()
        cur.append(w)
    flush()
    for i in range(len(cues) - 1):
        cues[i][1] = min(cues[i][1], cues[i + 1][0] - 0.01)
    cues[-1][1] = min(cues[-1][1], total)
    return "".join(f"{i+1}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(cues)), len(cues)


def hms(t):
    t = int(t)
    return f"{t//3600}:{(t%3600)//60:02d}:{t%60:02d}" if t >= 3600 else f"{t//60}:{t%60:02d}"


def build_metadata(plan, segs, total, flagged):
    tags, size = [], 0
    for tg in plan.get("tags", []):
        if size + len(tg) + 1 > 450:
            break
        tags.append(tg)
        size += len(tg) + 1
    chaps = []
    for sg in segs:
        if sg.get("label"):
            chaps.append((sg["rec"], sg["label"]))
    if chaps and chaps[0][0] > 0:
        chaps.insert(0, (0.0, "Intro"))
    lines = [f"TITLE:\n{plan['title']}\n", f"DESCRIPTION:\n{plan['description']}\n"]
    if chaps:
        lines.append("CHAPTERS:\n" + "\n".join(f"{hms(t)} {l}" for t, l in chaps) + "\n")
    lines.append("TAGS:\n" + ", ".join(tags) + "\n")
    if plan.get("hashtags"):
        lines.append("HASHTAGS:\n" + plan["hashtags"] + "\n")
    lines.append(f"RUNTIME: {hms(total)}\n")
    return "\n".join(lines)


def encode_segment(job):
    i, sg, plan, work = job
    out = work / f"seg_{i:04d}.mkv"
    if out.exists() and out.stat().st_size > 1000:
        return i, True, ""
    d = sg["end"] - sg["start"]
    fade = 0.012
    af = f"afade=t=in:d={fade},afade=t=out:st={max(d-fade,0):.3f}:d={fade}"
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{sg['start']:.3f}", "-t", f"{d:.3f}", "-i", plan["source"],
           "-map", "0:v:0", "-map", f"0:a:{plan.get('audio_stream', 0)}",
           "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "22", "-b:v", "0",
           "-maxrate", "12M", "-bufsize", "24M", "-g", "60", "-pix_fmt", "yuv420p", "-r", str(plan.get("fps", 30)),
           "-af", af, "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out) + ".part.mkv"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    part = Path(str(out) + ".part.mkv")
    if r.returncode != 0 or not part.exists():
        return i, False, r.stderr[-400:]
    part.replace(out)
    return i, True, ""


def render(plan, segs, final_mp4, workers=3):
    work = Path(plan["work_dir"])
    work.mkdir(parents=True, exist_ok=True)
    jobs = [(i, sg, plan, work) for i, sg in enumerate(segs)]
    bad = []
    done = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        for i, ok, err in ex.map(encode_segment, jobs):
            done += 1
            if not ok:
                bad.append((i, err))
            if done % 20 == 0 or done == len(jobs):
                print(f"  encoded {done}/{len(jobs)}", flush=True)
    if bad:
        print("SEGMENT FAILURES:", bad[:5])
        sys.exit(2)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{(work / f'seg_{i:04d}.mkv').as_posix()}'\n" for i in range(len(segs))))
    final_mp4.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_mp4.with_suffix(".tmp.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-800:])
        sys.exit(3)
    tmp.replace(final_mp4)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    plan = json.load(open(args[0], encoding="utf8"))
    name = plan["name"]
    job = Path(plan["job_dir"])
    out_dir = Path(plan["out_dir"])
    job.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    words = load_words(plan["words"])
    segs, total, excised = tighten(plan, words)
    excise_pats = [re.compile(p, re.I) for p in plan.get("excise", DEFAULT_EXCISE)]
    fps = plan.get("fps", 30)
    print(f"{name}: {len(plan['ranges'])} ranges -> {len(segs)} segments, {total/60:.1f} min "
          f"(raw ranges {sum(r[1]-r[0] for r in plan['ranges'])/60:.1f} min), excised {len(list(excised))} words")
    (job / f"{name}_cut.json").write_text(json.dumps(segs, indent=1))
    infos = []
    for sg in segs:
        infos.append({"start_frame": int(round(sg["start"] * fps)), "end_frame": int(round(sg["end"] * fps)),
                      "record_frame": int(round(sg["rec"] * fps))})
    (job / f"{name}_clip_infos.json").write_text(json.dumps(infos, indent=1))
    tw = remap_words(segs, words, excise_pats)
    srt, n = build_srt(tw, total)
    (out_dir / f"{plan['file_stem']}.srt").write_text(srt, encoding="utf8")
    flagged = [(w["start"], w["word"]) for w in tw if FLAG_RE.match(clean(w["word"]))]
    slurs = [(w["start"], w["word"]) for w in tw if SLUR_RE.match(clean(w["word"]))]
    (job / f"{name}_flagged_words.txt").write_text(
        "".join(f"{hms(t)}  {w}\n" for t, w in flagged) + ("\nSLURS:\n" + "".join(f"{hms(t)}  {w}\n" for t, w in slurs) if slurs else ""),
        encoding="utf8")
    (out_dir / f"{plan['file_stem']}_metadata.txt").write_text(build_metadata(plan, segs, total, flagged), encoding="utf8")
    print(f"  srt cues {n}; flagged words {len(flagged)}; SLURS {len(slurs)}")
    if slurs:
        print("  !! slurs present in cut:", slurs)
    if "--no-render" in sys.argv:
        return
    final = out_dir / f"{plan['file_stem']}.mp4"
    render(plan, segs, final)
    print("DONE", final)


if __name__ == "__main__":
    main()
