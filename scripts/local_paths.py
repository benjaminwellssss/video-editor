"""This machine's folders, from the git-ignored local_paths.json at the repo root (copy local_paths.example.json).

python local_paths.py prints the streaming folder, for shell scripts.
"""
import json
import os
import sys

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "local_paths.json")


def streaming(*parts):
    """A path under the streaming folder, which holds Videos, video-editor-projects, Overlays + Images and Sound Effects."""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            root = json.load(f)["streaming_root"]
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"Set streaming_root in {os.path.normpath(CONFIG)} (see local_paths.example.json): {e}")
    return os.path.join(root, *parts)


if __name__ == "__main__":
    print(streaming())
