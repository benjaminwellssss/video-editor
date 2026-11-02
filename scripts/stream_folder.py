"""Per-stream-date deliverables folder (user's system, 2026-10-30):

    <streaming-folder>\\Videos\\<MM-DD-YYYY> - <Game>[ + <Game>]\\
        VOD\\          raw recordings (+ CUTOUT cam files, full-VOD exports)
        Clips\\        PROOFS\\NN_name.mp4 first, then one folder per picked short
        Videos\\       finished long-forms (+ their .srt)
        Metadata\\     episode metadata.txt / tags / publish notes
        Thumbnails\\   only the chosen thumbN_final.jpg; caps, stickers, mockups etc. in Thumbnails\\Pieces
        Resolve\\      .drp exports, clip_infos, rendered panels

Subfolders are made only when something goes in them. One folder per date: a second game the same night shares it.
Usage: python stream_folder.py <MM-DD-YYYY|YYYY-MM-DD> [game] [sub]   prints the path (creating it)
"""
from local_paths import streaming
import os
import re
import sys

VIDEOS = streaming(r"Videos")
SUBS = ("VOD", "Clips", "Videos", "Metadata", "Thumbnails", "Resolve")


def norm_date(d):
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", d)
    d = f"{m.group(2)}-{m.group(3)}-{m.group(1)}" if m else d
    assert re.fullmatch(r"\d\d-\d\d-\d{4}", d), f"date must be MM-DD-YYYY or YYYY-MM-DD, got {d!r}"
    return d


def stream_dir(date, game=None, sub=None, root=VIDEOS):
    """The date's folder (an existing one wins, whatever games it names), plus sub, created on demand."""
    date = norm_date(date)
    have = [f for f in os.listdir(root) if f.startswith(date + " - ") and os.path.isdir(os.path.join(root, f))]
    assert len(have) <= 1, f"two folders for {date}: {have}"
    if not have:
        assert game, f"no folder for {date} yet: pass the game"
    path = os.path.join(root, have[0] if have else f"{date} - {game}")
    if sub:
        assert sub.split(os.sep)[0].split("/")[0] in SUBS, f"sub must start with one of {SUBS}"
        path = os.path.join(path, sub)
    os.makedirs(path, exist_ok=True)
    return path


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            a = stream_dir("2026-10-30", "Arc Raiders", "Clips/PROOFS", root=t)
            assert a == os.path.join(t, "10-30-2026 - Arc Raiders", "Clips/PROOFS") and os.path.isdir(a)
            assert stream_dir("10-30-2026", "Valheim", "VOD", root=t) == os.path.join(t, "10-30-2026 - Arc Raiders", "VOD")
            try:
                stream_dir("10-31-2026", root=t)
                raise SystemExit("expected a missing-game error")
            except AssertionError:
                pass
        print("selftest ok")
    else:
        print(stream_dir(*sys.argv[1:4]))
