"""Transcribe a raw clip with WhisperX, word-level timestamps, cached forever.

Usage: <venv-python> scripts/transcribe.py <path-to-media> <path-to-words.json>
"""
import json
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")

import torch
import whisperx

def main():
    media_path = sys.argv[1]
    out_path = sys.argv[2]

    if os.path.exists(out_path):
        print("already transcribed, skipping:", out_path)
        return

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

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("wrote", out_path)

if __name__ == "__main__":
    main()
