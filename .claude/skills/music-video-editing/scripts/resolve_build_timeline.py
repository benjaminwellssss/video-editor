"""Build a Resolve timeline directly over the in-app bridge, from a JSON file.

Exists to avoid pasting a huge clip_infos array (hundreds of entries) through
the chat tool-call interface, which burns a large amount of context for a
long curated edit. Does exactly what the davinci-resolve MCP's
create_timeline_from_clips(clip_infos=...) tool does under the hood
(CreateEmptyTimeline + AppendToTimeline), just driven from a file instead.

Usage:
    resolve_build_timeline.py <clip_infos.json> <timeline_name> [if_exists]

<clip_infos.json>: a JSON array of {"clip_id", "start_frame", "end_frame",
    "record_frame"} objects, source frames at the raw clip's own frame rate,
    record_frame relative to the new timeline's start. Same shape produced by
    scripts/build_scene_cut.py.
if_exists: "version" (default, appends " vNN" if the name is taken) or "fail".

Requires DaVinci Resolve open with the in-app bridge running (Workspace >
Scripts > resolve_bridge, or the Console exec fallback per project memory),
and a project open with clip_id already imported into the media pool.
"""
import json
import os
import sys
from pathlib import Path

# repo root is four levels up: scripts -> music-video-editing -> skills -> .claude -> repo
VENDOR_ROOT = Path(__file__).resolve().parents[4] / "vendor" / "davinci-resolve-mcp"
sys.path.insert(0, str(VENDOR_ROOT))
os.environ["DAVINCI_RESOLVE_BRIDGE"] = "1"

from src.utils import resolve_bridge_client as bridge_client  # noqa: E402


def find_clip_by_id(folder, target_id):
    for clip in (folder.GetClipList() or []):
        if clip.GetUniqueId() == target_id:
            return clip
    for sub in (folder.GetSubFolderList() or []):
        found = find_clip_by_id(sub, target_id)
        if found:
            return found
    return None


def existing_timeline_names(project):
    names = set()
    count = project.GetTimelineCount() or 0
    for i in range(1, count + 1):
        tl = project.GetTimelineByIndex(i)
        if tl:
            names.add(tl.GetName())
    return names


def resolve_name(project, requested, if_exists):
    taken = existing_timeline_names(project)
    if requested not in taken:
        return requested
    if if_exists == "fail":
        raise SystemExit(f"Timeline '{requested}' already exists (if_exists=fail)")
    n = 2
    while f"{requested} v{n:02d}" in taken:
        n += 1
    return f"{requested} v{n:02d}"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    clip_infos_path, timeline_name = sys.argv[1], sys.argv[2]
    if_exists = sys.argv[3] if len(sys.argv) > 3 else "version"

    with open(clip_infos_path, encoding="utf-8") as f:
        clip_infos = json.load(f)
    if not isinstance(clip_infos, list) or not clip_infos:
        raise SystemExit("clip_infos JSON must be a non-empty array")

    resolve = bridge_client.connect()
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise SystemExit("No project currently open in Resolve")
    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    # Resolve each unique clip_id once.
    clip_cache = {}
    for ci in clip_infos:
        cid = ci["clip_id"]
        if cid not in clip_cache:
            clip = find_clip_by_id(root, cid)
            if not clip:
                raise SystemExit(f"Media pool clip not found: {cid}")
            clip_cache[cid] = clip

    final_name = resolve_name(project, timeline_name, if_exists)
    tl = mp.CreateEmptyTimeline(final_name)
    if not tl:
        raise SystemExit("Failed to create empty timeline")
    if not project.SetCurrentTimeline(tl):
        raise SystemExit("Failed to set the new timeline as current (required before AppendToTimeline)")

    timeline_start = int(round(tl.GetStartFrame()))

    # A new timeline has one video track; layered edits need the rest added first.
    want_tracks = max(int(ci.get("track_index", 1)) for ci in clip_infos)
    while (tl.GetTrackCount("video") or 0) < want_tracks:
        if not tl.AddTrack("video"):
            raise SystemExit(f"Failed to add video track {tl.GetTrackCount('video') + 1}")

    built = []
    for ci in clip_infos:
        built.append({
            "mediaPoolItem": clip_cache[ci["clip_id"]],
            "startFrame": int(ci["start_frame"]),
            "endFrame": int(ci["end_frame"]),
            "recordFrame": timeline_start + int(ci["record_frame"]),
            "trackIndex": int(ci.get("track_index", 1)),
        })

    appended = mp.AppendToTimeline(built)
    if not appended:
        raise SystemExit("AppendToTimeline failed")

    end_frame = int(round(tl.GetEndFrame()))
    print(json.dumps({
        "success": True,
        "timeline_name": tl.GetName(),
        "timeline_id": tl.GetUniqueId(),
        "clip_count": len(built),
        "start_frame": timeline_start,
        "end_frame": end_frame,
        "duration_frames": end_frame - timeline_start,
    }, indent=2))


if __name__ == "__main__":
    main()
