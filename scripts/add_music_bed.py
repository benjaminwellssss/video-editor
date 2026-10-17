"""Lay one continuous stretch of background music under a finished video, levelled against the game track.

Usage: python add_music_bed.py <video.mp4> <music> --ref <game_track> [--ref-start S] [--ratio 0.75]
                               [--offset S] [--out <out.mp4>]

The music's typical peaks land at --ratio of the game track's typical peaks (the same measure as
level_game_audio.py), so "music at 75% of the game" stays repeatable from video to video. --ref is the levelled
game track the video's audio was built from; --offset picks where in the music file to start. Video is copied
untouched; without --out the video is replaced in place once the new file is written.
"""
import argparse
import subprocess
from pathlib import Path

import numpy as np

from level_game_audio import gain_db, peaks, typical_peak

FADE_IN, FADE_OUT = 2.0, 4.0


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True, check=True).stdout)


def music_peaks(path, start, length):
    p = peaks(path, start)
    return p[: int(length * 10)]  # peaks() reads to the end; keep only the stretch we use (0.1 s windows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"), ap.add_argument("music")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--ref-start", type=float, default=0)
    ap.add_argument("--ratio", type=float, default=0.75)
    ap.add_argument("--offset", type=float, default=0)
    ap.add_argument("--out")
    a = ap.parse_args()

    dur = duration(a.video)
    assert a.offset + dur <= duration(a.music), "music stretch runs past the end of the music file"
    rp, mp = typical_peak(peaks(a.ref, a.ref_start)), typical_peak(music_peaks(a.music, a.offset, dur))
    g = gain_db(rp, mp, a.ratio)
    print(f"game typical peak {20 * np.log10(rp):.1f} dB, music {20 * np.log10(mp):.1f} dB"
          f" -> music {g:+.1f} dB (peaks at {a.ratio:.0%} of game)")

    out = Path(a.out or a.video)
    tmp = out.with_suffix(".music.tmp.mp4")
    bed = f"volume={g:.2f}dB,afade=t=in:d={FADE_IN},afade=t=out:st={dur - FADE_OUT:.2f}:d={FADE_OUT}"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", a.video,
                    "-ss", str(a.offset), "-t", f"{dur:.3f}", "-i", a.music,
                    "-filter_complex", f"[1:a]{bed}[b];[0:a][b]amix=inputs=2:normalize=0:duration=first,"
                                       "alimiter=limit=0.95:level=disabled[m]",
                    "-map", "0:v", "-map", "[m]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(out)
    print("wrote", out)


if __name__ == "__main__":
    assert abs(gain_db(0.2, 0.3, 0.75) - (-6.02)) < 0.01  # 0.3 -> 0.15 = 75% of a 0.2 game peak
    main()
