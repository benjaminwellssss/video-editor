"""Small ffprobe helpers shared by the pipeline scripts.

video_fps(path): the video stream's nominal frame rate (30.0, 60.0, 29.97...). Recordings were 30 fps until
2026-10-24 and 60 fps after, so scripts read the rate from the source instead of assuming 30.
"""
import subprocess
import sys
from fractions import Fraction


def video_fps(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.split()[0]  # ffprobe 9 can print the stream twice (stream group)
    return float(Fraction(r))


if __name__ == "__main__":
    assert float(Fraction("60/1")) == 60.0 and round(float(Fraction("30000/1001")), 2) == 29.97
    for p in sys.argv[1:]:
        print(p, video_fps(p))
