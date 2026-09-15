"""Transcribe a raw clip with WhisperX (word-level timestamps) AND run speaker
diarization, tagging each word with a "speaker" label. Cached forever, same
as transcribe.py, but the output words carry a "speaker" field so downstream
caption-building can show only the currently-talking speaker (and detect
overlapping speech for a dual-caption layout).

Requires an HF_TOKEN env var with read access to the gated
pyannote/speaker-diarization-community-1 model (accept its terms at
https://hf.co/pyannote/speaker-diarization-community-1 first).

Usage: HF_TOKEN=... <venv-python> scripts/transcribe_diarized.py <path-to-media> <path-to-words.json> [min_speakers] [max_speakers]
"""
import json
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")

import torch
import whisperx
from whisperx.diarize import DiarizationPipeline, assign_word_speakers


def main():
    media_path = sys.argv[1]
    out_path = sys.argv[2]
    min_speakers = int(sys.argv[3]) if len(sys.argv) > 3 else None
    max_speakers = int(sys.argv[4]) if len(sys.argv) > 4 else None

    if os.path.exists(out_path):
        print("already transcribed, skipping:", out_path)
        return

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("HF_TOKEN env var not set — required for diarization.")
        sys.exit(1)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print("device:", device, "compute_type:", compute_type)

    try:
        model = whisperx.load_model("large-v3", device, compute_type=compute_type)
        audio = whisperx.load_audio(media_path)
        result = model.transcribe(audio, batch_size=16)
    except Exception as e:
        print("CUDA path failed (%s), falling back to CPU int8" % e)
        device = "cpu"
        compute_type = "int8"
        model = whisperx.load_model("large-v3", device, compute_type=compute_type)
        audio = whisperx.load_audio(media_path)
        result = model.transcribe(audio, batch_size=16)

    align_model, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
    result = whisperx.align(result["segments"], align_model, metadata, audio, device, return_char_alignments=False)

    print("running diarization...")
    diarize_model = DiarizationPipeline(token=hf_token, device=device)
    diarize_kwargs = {}
    if min_speakers is not None:
        diarize_kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        diarize_kwargs["max_speakers"] = max_speakers
    diarize_segments = diarize_model(audio, **diarize_kwargs)
    result = assign_word_speakers(diarize_segments, result)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("wrote", out_path)


if __name__ == "__main__":
    main()
