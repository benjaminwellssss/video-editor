"""Level a stream's game/music track against its voices: the game's typical peaks land at a set fraction of
the voices' typical peaks (default 50%), then write the boosted game track and, optionally, voices + game mixed.

Usage: python level_game_audio.py <voices.m4a> <game.m4a> <game_out.m4a> [--ratio 0.5] [--mix <mix_out.m4a>]
                                  [--start <seconds>]

"Typical peak" = the mean of the loudest 10% of 0.1 s peak readings, ignoring the loudest 0.05% (a single
blip shouldn't set the level). OBS sometimes records the game far too quietly (10-14 sat about 38 dB under the
voices); this brings it back to a fixed, repeatable balance. A limiter keeps the loudest hits from clipping.
--start skips a silent lead-in so it doesn't skew the measurement.
"""
import argparse
import subprocess

import numpy as np

SR, WIN = 8000, 800  # 0.1 s windows


def peaks(path, start):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", path, "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.abs(np.frombuffer(raw, dtype=np.int16).astype(float)) / 32768
    k = len(x) // WIN
    return x[:k * WIN].reshape(k, WIN).max(1)


def typical_peak(p):
    p = np.sort(p)
    p = p[: int(len(p) * 0.9995)]
    return float(p[int(len(p) * 0.9):].mean())


def gain_db(voice_peak, game_peak, ratio):
    return 20 * np.log10(ratio * voice_peak / game_peak)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("voices"), ap.add_argument("game"), ap.add_argument("game_out")
    ap.add_argument("--ratio", type=float, default=0.5)
    ap.add_argument("--mix")
    ap.add_argument("--start", type=float, default=0)
    a = ap.parse_args()
    vp, gp = typical_peak(peaks(a.voices, a.start)), typical_peak(peaks(a.game, a.start))
    g = gain_db(vp, gp, a.ratio)
    print(f"voices typical peak {20 * np.log10(vp):.1f} dB, game {20 * np.log10(gp):.1f} dB -> game {g:+.1f} dB "
          f"(peaks at {a.ratio:.0%} of voice)")
    lim = "alimiter=limit=0.95:level=disabled"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", a.game, "-af", f"volume={g:.2f}dB,{lim}",
                    "-c:a", "aac", "-b:a", "192k", a.game_out], check=True)
    if a.mix:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", a.voices, "-i", a.game_out, "-filter_complex",
                        f"[0:a][1:a]amix=inputs=2:normalize=0,{lim}[m]", "-map", "[m]", "-c:a", "aac", "-b:a", "192k",
                        a.mix], check=True)
    print("wrote", a.game_out, "and " + a.mix if a.mix else "")


if __name__ == "__main__":
    assert abs(gain_db(0.4, 0.004, 0.5) - 33.98) < 0.01  # half of a 40 dB gap
    main()
