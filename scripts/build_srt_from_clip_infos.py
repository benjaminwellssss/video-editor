"""Build an SRT for a cut-down timeline straight from a full-VOD word transcript
and the clip_infos list used to build that timeline (no Resolve needed), so
captions are ready the moment the timeline exists.

Usage: python build_srt_from_clip_infos.py <words.json> <clip_infos.json> <fps> <out.srt>

clip_infos: [{"start_frame", "end_frame" (exclusive, SOURCE frames at <fps>),
"record_frame" (timeline-relative frame)}, ...] - the same shape
build_scene_cut.py writes and resolve_build_timeline.py consumes.

A word is kept only if it lies fully inside a clip, so anything excised from the
edit (censored words, cut scenes) never reaches the captions. Subtitles always
break at a clip boundary (a cut means new text), at pauses over a second, at
~10 words / 4s, and at sentence ends once there are a few words.
"""
import bisect
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
    words_path, infos_path, fps, out_path = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    full = json.load(open(words_path, encoding="utf-8"))
    words = sorted(
        (w for s in full["segments"] for w in s.get("words", []) if "start" in w and "end" in w),
        key=lambda w: w["start"],
    )
    starts = [w["start"] for w in words]
    infos = json.load(open(infos_path, encoding="utf-8"))

    chunks = []  # (start_s, end_s, text) on the edited timeline
    for ci in infos:
        a, b = ci["start_frame"] / fps, ci["end_frame"] / fps
        base = ci["record_frame"] / fps - a  # source seconds -> timeline seconds
        lo = bisect.bisect_left(starts, a)
        cur = []

        def flush():
            if cur:
                chunks.append((cur[0][0], cur[-1][1], " ".join(t for _, _, t in cur)))
                cur.clear()

        for w in words[lo:]:
            if w["start"] >= b:
                break
            if w["end"] > b:
                continue
            ws, we = w["start"] + base, w["end"] + base
            text = w["word"].strip()
            if not text:
                continue
            if cur and (ws - cur[-1][1] > GAP_BREAK_SECONDS or we - cur[0][0] > MAX_CHUNK_SECONDS
                        or len(cur) >= MAX_CHUNK_WORDS):
                flush()
            cur.append((ws, we, text))
            if text[-1] in ".?!" and len(cur) >= MIN_WORDS_FOR_SENTENCE_BREAK:
                flush()
        flush()

    chunks.sort()
    with open(out_path, "w", encoding="utf-8") as f:
        for i, (s, e, text) in enumerate(chunks, 1):
            nxt = chunks[i][0] if i < len(chunks) else None
            e = min(e + 0.15, nxt - 0.02) if nxt is not None else e + 0.15  # brief hold, never overlapping the next line
            e = max(e, s + 0.2)
            f.write(f"{i}\n{tc(s)} --> {tc(e)}\n{text}\n\n")
    print(f"{len(chunks)} subtitles across {len(infos)} clips -> {out_path}")


if __name__ == "__main__":
    main()
