"""Turn a hand-picked list of moments into finished-clip deliverables (everything
except caption compositing): per clip a folder with the video, single-word
captions.json, captions.srt and metadata.txt.

Usage: python prep_shorts_batch.py <plan.json> [--no-render]

plan.json:
{
  "words": "<whisperx words json (nested segments/words)>",
  "source": "<mp4>", "audio_stream": 0,
  "face_crop": [w,h,x,y], "fg_height": 1080, "fg_bottom_aligned": false,
  "handle": "<handles gif>",
  "out_dir": "E:/Streaming/Videos/Clips/<MM-DD-YYYY_GAME>",
  "work_dir": "<scratch dir>", "job_dir": "<project job shorts dir for segment files>",
  "base_tags": ["valheim funny moments", ...],
  "hashtags": "#Valheim #FunnyGaming ...",
  "clips": [{"name", "title", "description", "tags_extra": [..], "ranges": [[a,b], ...]}]
}

Each range is tightened to the words inside it: speech gaps over 2s are cut out
(0.3s lead / 0.4s tail kept). Curse words/slurs are NOT cut (user decision
2026-10-03: censor later); they are listed in <plan>_flagged_words.txt.
Then runs build_blurstack_batch.py for the video (unless --no-render).
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FLAGGED = []
GAP, LEAD, TAIL = 2.0, 0.30, 0.40
CURSE = re.compile(r"^(f[\.\-\u2026\*]+|f+u+c+k+\w*|f+k+\w*)$", re.I)
SLUR = re.compile(r"n[i1]gg|fag+ot|retard|chink|kike|spic\b|tranny", re.I)


def load_words(path):
    data = json.load(open(path, encoding="utf-8"))
    ws = [w for s in data["segments"] for w in s.get("words", []) if "start" in w and "end" in w]
    return sorted(ws, key=lambda w: w["start"])


def clean(tok):
    return re.sub(r"[^A-Za-z0-9'\.\-\u2026\*]", "", tok)


def plan_segments(words, ranges, name):
    segs = []
    for a, b in ranges:
        ws = [w for w in words if w["start"] >= a - 0.05 and w["end"] <= b + 0.05]
        if not ws:
            segs.append([a, b])
            continue
        runs, cur, prev = [], ws[0]["start"], ws[0]
        for w in ws[1:]:
            if w["start"] - prev["end"] > GAP:
                runs.append([cur, prev["end"]])
                cur = w["start"]
            prev = w
        runs.append([cur, prev["end"]])
        for s, e in runs:
            segs.append([round(s - LEAD, 3), round(e + TAIL, 3)])
    # Flagged words are kept in the clip (the user censors them later); just report them.
    for w in words:
        t = clean(w["word"])
        if (SLUR.search(t) or CURSE.match(t)) and any(s <= w["start"] and w["end"] <= e for s, e in segs):
            kind = "SLUR" if SLUR.search(t) else "curse"
            FLAGGED.append(f"{name}: {kind} '{t}' at source {w['start']:.1f}s")
    return segs


def srt_from_cards(cards_path, srt_path):
    subprocess.run([sys.executable, os.path.join(HERE, "build_srt_from_cards.py"), cards_path, srt_path],
                   check=True, stdout=subprocess.DEVNULL)


def write_metadata(path, clip, plan):
    tags = list(plan["base_tags"]) + list(clip.get("tags_extra", []))
    tag_str = ", ".join(tags)
    body = (
        f"TITLE:\n{clip['title']}\n\nDESCRIPTION:\n{clip['description']}\n\n{plan['hashtags']}\n\n"
        f"TAGS (comma-separated, {len(tag_str)}/450 chars):\n{tag_str}\n"
    )
    assert len(tag_str) <= 450, f"{clip['name']}: tags over 450 chars"
    open(path, "w", encoding="utf-8").write(body)


def main():
    plan = json.load(open(sys.argv[1], encoding="utf-8"))
    render = "--no-render" not in sys.argv
    words = load_words(plan["words"])
    os.makedirs(plan["job_dir"], exist_ok=True)
    os.makedirs(plan["work_dir"], exist_ok=True)
    spec_clips = []
    for clip in plan["clips"]:
        name = clip["name"]
        segs = plan_segments(words, clip["ranges"], name)
        dur = sum(e - s for s, e in segs)
        print(f"{name}: {len(segs)} segments, {dur:.1f}s")
        seg_path = os.path.join(plan["job_dir"], name + "_segments.json")
        json.dump([{"start": s, "end": e} for s, e in segs], open(seg_path, "w"), indent=1)
        spec_clips.append({"name": name, "segments": segs})
        out = os.path.join(plan["out_dir"], name)
        os.makedirs(out, exist_ok=True)
        cards = os.path.join(out, "captions.json")
        subprocess.run([sys.executable, os.path.join(HERE, "build_short_cards_from_segments.py"),
                        seg_path, plan["words"], cards, "single"], check=True, stdout=subprocess.DEVNULL)
        srt_from_cards(cards, os.path.join(out, "captions.srt"))
        write_metadata(os.path.join(out, "metadata.txt"), clip, plan)
    if FLAGGED:
        rpt = os.path.join(plan["job_dir"], os.path.basename(sys.argv[1]).replace(".json", "_flagged_words.txt"))
        open(rpt, "w", encoding="utf-8").write("\n".join(FLAGGED) + "\n")
        print(len(FLAGGED), "flagged words kept in clips ->", rpt)
    spec = {k: plan[k] for k in ("source", "handle", "face_crop", "fg_height", "fg_bottom_aligned", "out_dir", "work_dir")}
    spec["audio_stream"] = plan.get("audio_stream", 0)
    spec["clips"] = spec_clips
    spec_path = os.path.join(plan["job_dir"], os.path.basename(sys.argv[1]).replace(".json", "_buildspec.json"))
    json.dump(spec, open(spec_path, "w"), indent=1)
    print("buildspec:", spec_path)
    if render:
        subprocess.run([sys.executable, os.path.join(HERE, "build_blurstack_batch.py"), spec_path], check=True)


if __name__ == "__main__":
    main()
