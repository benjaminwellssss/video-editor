"""Resumable WhisperX transcription for very long audio: 30-minute chunks (with a
5s overlap on each side so edge words are never lost), each saved as soon as it
finishes, then merged into one words json in the same nested shape transcribe.py
writes ({"segments": [{"words": [...]}]}).

Usage: <venv-python> scripts/transcribe_chunked.py <media> <out_words.json> [chunk_seconds]
Re-running skips chunks that already exist. <out>.partial.json is refreshed after
every chunk so early parts can be used while the rest is still running.
"""
import glob
import json
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
import torch
import whisperx

SR = 16000
OVERLAP = 5.0


def merge(chunk_dir, out_path):
    words = []
    for f in sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.json"))):
        words.extend(json.load(open(f, encoding="utf-8")))
    words.sort(key=lambda w: w["start"])
    json.dump({"segments": [{"words": words}]}, open(out_path, "w", encoding="utf-8"))
    return len(words)


def main():
    media, out_path = sys.argv[1], sys.argv[2]
    chunk_s = float(sys.argv[3]) if len(sys.argv) > 3 else 1800.0
    chunk_dir = os.path.splitext(out_path)[0] + "_chunks"
    os.makedirs(chunk_dir, exist_ok=True)

    audio = whisperx.load_audio(media)
    total = len(audio) / SR
    n = int(total // chunk_s) + (1 if total % chunk_s > 1 else 0)
    print(f"audio {total:.0f}s, {n} chunks", flush=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    ct = "float16" if device == "cuda" else "int8"
    model = whisperx.load_model("large-v3", device, compute_type=ct, language="en")
    align_model, meta = whisperx.load_align_model(language_code="en", device=device)

    for k in range(n):
        cf = os.path.join(chunk_dir, f"chunk_{k:02d}.json")
        if os.path.exists(cf):
            continue
        keep_lo, keep_hi = k * chunk_s, min((k + 1) * chunk_s, total + 1)
        lo = max(0.0, keep_lo - OVERLAP)
        hi = min(total, keep_hi + OVERLAP)
        seg = audio[int(lo * SR):int(hi * SR)]
        res = model.transcribe(seg, batch_size=16)
        res = whisperx.align(res["segments"], align_model, meta, seg, device, return_char_alignments=False)
        words = []
        for s in res["segments"]:
            for w in s.get("words", []):
                if "start" not in w or "end" not in w:
                    continue
                st = w["start"] + lo
                if keep_lo <= st < keep_hi:
                    words.append({"word": w["word"], "start": round(st, 3), "end": round(w["end"] + lo, 3),
                                  "score": w.get("score")})
        json.dump(words, open(cf, "w", encoding="utf-8"))
        cnt = merge(chunk_dir, out_path + ".partial.json")
        print(f"chunk {k + 1}/{n} done ({len(words)} words, {cnt} total)", flush=True)

    cnt = merge(chunk_dir, out_path)
    print(f"DONE {cnt} words -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
