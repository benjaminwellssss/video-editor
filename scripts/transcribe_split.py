"""Per-speaker transcript of a short from the split audio tracks: Ben's mic and the clean Discord feed, each transcribed alone.

Mixed-track transcription (and diarization of the mix) blurs who said what; the mic track is only Ben and the Discord track
is only everyone else, so the speaker comes from the track, not a guess (stream-vod-edit: 4-track layout since 2026-10-09,
ffmpeg audio index 1 = Ben's mic, 2 = Discord).

Usage: <whisperx-venv-python> transcribe_split.py <name_cut.json> <source.mp4 per part: part=path ...> <out_words.json>
    e.g. ... SC1_cut.json 3="<vod-folder>/22-05-09.mp4" SC1_split_words.json
Output: {"segments": [{"words": [{"word","start","end","speaker"}]}]} in CLIP time; speaker is "Ben" or "Discord".
Then build_caption_cards_split.py (or words_to_cards per speaker) turns it into cards.
"""
import json
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch  # noqa: E402
import whisperx  # noqa: E402

from protected_names import scrub  # noqa: E402

TRACKS = {"Ben": 1, "Discord": 2}   # ffmpeg audio stream index
PAD_S = 0.4                          # context either side of each cut piece; words outside the piece are dropped afterwards
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
_models = {}


def models():
    if not _models:
        ct = "float16" if DEVICE == "cuda" else "int8"
        _models["asr"] = whisperx.load_model("large-v3", DEVICE, compute_type=ct)
        _models["align"] = whisperx.load_align_model(language_code="en", device=DEVICE)
    return _models


def piece_words(src, track, a, b):
    """Words spoken on one audio track between source seconds a..b, in source time."""
    wav = os.path.join(tempfile.gettempdir(), "split_piece.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src, "-map", f"0:a:{track}",
                    "-ac", "1", "-ar", "16000", wav], check=True)
    m = models()
    audio = whisperx.load_audio(wav)
    res = m["asr"].transcribe(audio, batch_size=16, language="en")
    if not res["segments"]:
        return []
    res = whisperx.align(res["segments"], m["align"][0], m["align"][1], audio, DEVICE, return_char_alignments=False)
    scrub(res)
    return [{"word": w["word"], "start": w["start"] + a, "end": w["end"] + a}
            for s in res["segments"] for w in s.get("words", []) if "start" in w and "end" in w]


def main():
    cut_path, out_path = sys.argv[1], sys.argv[-1]
    srcs = {int(k): v for k, v in (kv.split("=", 1) for kv in sys.argv[2:-1])}
    d = json.load(open(cut_path, encoding="utf-8"))
    fps = d["fps"]
    out = []
    for rec_a, rec_b, src_frame, part in d["cut"]:
        a, b = src_frame / fps, (src_frame + rec_b - rec_a) / fps
        rec0 = rec_a / fps
        for who, track in TRACKS.items():
            for w in piece_words(srcs[part], track, max(0, a - PAD_S), b + PAD_S):
                if w["start"] >= a - 0.05 and w["end"] <= b + 0.05:
                    out.append({"word": w["word"], "start": round(w["start"] - a + rec0, 3),
                                "end": round(w["end"] - a + rec0, 3), "speaker": who})
    out.sort(key=lambda w: w["start"])
    json.dump({"segments": [{"words": out}]}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n = {k: sum(1 for w in out if w["speaker"] == k) for k in TRACKS}
    print(out_path, n)


if __name__ == "__main__":
    main()
