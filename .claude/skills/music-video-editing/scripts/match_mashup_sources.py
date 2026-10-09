"""Work out which source song (and where in it) each stretch of a mashup comes from.

Matches the mashup's own Demucs stems against each source song's stems, with the
source stretched to the mashup tempo, in short sliding windows. Chroma stems
(vocals/bass/other) also try every transposition, so a pitched clip still matches.

usage: match_mashup_sources.py <mashup_stems_dir> <mashup_bpm> <start_s> <out.json>
                               <name>=<stems_dir>=<bpm> [...]
"""
import json
import sys

import librosa
import numpy as np
from scipy.signal import fftconvolve

SR = 22050
HOP = 512
DT = HOP / SR
STEMS = ["vocals", "bass", "other", "drums"]


def feats(path, stem):
    y, _ = librosa.load(path, sr=SR, mono=True)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    if stem == "drums":
        f = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)[None, :]
    else:
        f = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    return f, rms[: f.shape[1]]


def stretch(f, factor):
    """Resample along time so one source frame lasts `factor` mashup frames."""
    n = int(round(f.shape[1] * factor))
    x = np.linspace(0, f.shape[1] - 1, n)
    return np.stack([np.interp(x, np.arange(f.shape[1]), row) for row in f])


def zn(w):
    w = w - w.mean(axis=1, keepdims=True)
    return w / (np.linalg.norm(w) + 1e-9)


def best_match(win, src, transpose):
    """Normalised cross-correlation of window `win` against every offset of `src`."""
    L = win.shape[1]
    w = zn(win)
    best = (-1.0, 0, 0)
    # local energy of src for normalisation
    s0 = src - src.mean(axis=1, keepdims=True)
    energy = fftconvolve((s0 ** 2).sum(axis=0), np.ones(L), mode="valid")
    shifts = range(-6, 6) if transpose else [0]
    for k in shifts:
        s = np.roll(s0, k, axis=0) if k else s0
        c = sum(fftconvolve(s[b], w[b][::-1], mode="valid") for b in range(s.shape[0]))
        c = c / (np.sqrt(np.maximum(energy, 1e-9)))
        j = int(np.argmax(c))
        if c[j] > best[0]:
            best = (float(c[j]), j, k)
    return best


def main():
    mdir, mbpm, start, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    songs = []
    for a in sys.argv[5:]:
        name, d, bpm = a.split("=")
        songs.append((name, d, float(bpm)))

    bar = 4 * 60 / mbpm
    win_s, hop_s = bar, bar / 2
    m = {s: feats(f"{mdir}/{s}.wav", s) for s in STEMS}
    src = {}
    for name, d, bpm in songs:
        factor = bpm / mbpm  # source beats are shorter/longer than mashup beats
        src[name] = {s: stretch(feats(f"{d}/{s}.wav", s)[0], factor) for s in STEMS}

    total = m["vocals"][0].shape[1] * DT
    rows = []
    t = start
    while t + win_s <= total:
        i, L = int(t / DT), int(win_s / DT)
        row = {"t": round(t, 3), "bar": round((t - start) / bar + 1, 2), "stems": {}}
        for s in STEMS:
            f, rms = m[s]
            level = float(20 * np.log10(rms[i:i + L].mean() + 1e-9))
            entry = {"db": round(level, 1), "match": {}}
            if level > -45:
                for name, d, bpm in songs:
                    score, j, k = best_match(f[:, i:i + L], src[name][s], s != "drums")
                    src_t = j * DT * mbpm / bpm  # stretched frame -> source seconds
                    entry["match"][name] = {"score": round(score, 3), "src_t": round(src_t, 2), "semi": k}
            row["stems"][s] = entry
        rows.append(row)
        t += hop_s
    json.dump(rows, open(out, "w"), indent=1)
    print(f"{len(rows)} windows -> {out}")


if __name__ == "__main__":
    main()
