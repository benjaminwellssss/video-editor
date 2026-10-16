#!/usr/bin/env python3
"""Build one 3-track 16:9 Resolve timeline per group of related shorts.

Drives the in-app bridge through its native-API proxy (src.utils.resolve_bridge_client),
so it needs Resolve running with the bridge up and the target project open.

Usage:
    python scripts/build_group_timelines.py <groups.json> [group name ...]

groups.json = list of {"name", "kind": "n"|"n_window"|"dw", "clip_id" (media pool item id),
                       "infos": [{start_frame,end_frame,record_frame}], "markers": [[rec_frame, label]]}

Layout recipe (1920x1080 timeline, then a centered 608x1080 crop to 9:16):
    V1 (audio too) blurred bg zoom 2.12 | V2 gameplay zoom 0.84 tilt -88 | V3 facecam, per FACE:
    "n"        the user's current format (2026-10-13): the bare webcam picture - the facecam.exe
               window's title bar, border and LIVE bar cropped away - zoomed to the full 9:16 width
               and sitting at the top. For the 462x320 facecam window at the bottom-right.
    "n_window" the older format: the whole facecam.exe window, unscaled (same 462x320 window).
    "dw"       the older format for Deadweight's taller 462x397 window.
The blur on V1 is not an API property; it is applied by hand in Resolve.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "davinci-resolve-mcp"))
from src.utils.resolve_bridge_client import connect  # noqa: E402

FACE = {
    "n": {"Pan": -1106, "Tilt": 914, "ZoomX": 1.53, "ZoomY": 1.53,
          "CropLeft": 1472, "CropRight": 18, "CropTop": 776, "CropBottom": 69},
    "n_window": {"Pan": -727, "Tilt": 757.0, "CropLeft": 1458, "CropTop": 760.5},
    "dw": {"Pan": -727, "Tilt": 679.5, "CropLeft": 1458, "CropTop": 683.0},
}


def find_clip(folder, clip_id):
    for c in folder.GetClipList():
        if c.GetUniqueId() == clip_id:
            return c
    raise SystemExit(f"media pool item {clip_id} not found")


def build(project, pool, group):
    name = group["name"]
    clip = find_clip(pool.GetRootFolder(), group["clip_id"])
    tl = None
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t.GetName() == name:
            tl = t
            old = []
            for tt, n in (("video", t.GetTrackCount("video")), ("audio", t.GetTrackCount("audio"))):
                for k in range(1, n + 1):
                    old += t.GetItemListInTrack(tt, k) or []
            if old:
                print(f"  {name}: clearing {len(old)} existing items before rebuild")
                t.DeleteClips(old, False)
                t.DeleteMarkersByColor("All")
    if tl is None:
        tl = pool.CreateEmptyTimeline(name)
    project.SetCurrentTimeline(tl)
    while tl.GetTrackCount("video") < 3:
        tl.AddTrack("video")
    start = tl.GetStartFrame()
    infos = []
    for track in (1, 2, 3):
        for c in group["infos"]:
            d = {"mediaPoolItem": clip, "startFrame": c["start_frame"], "endFrame": c["end_frame"],
                 "recordFrame": start + c["record_frame"], "trackIndex": track}
            if track > 1:
                d["mediaType"] = 1
            infos.append(d)
    res = pool.AppendToTimeline(infos)
    n = len(group["infos"])
    if not res or len(res) != 3 * n:
        raise SystemExit(f"{name}: appended {len(res) if res else 0}, expected {3*n}")
    face = FACE[group["kind"]]
    bad = 0
    for track in (1, 2, 3):
        items = tl.GetItemListInTrack("video", track)
        if len(items) != n:
            raise SystemExit(f"{name}: track {track} has {len(items)} items, expected {n}")
        for it in items:
            if track == 1:
                ok = it.SetProperty("ZoomX", 2.12) and it.SetProperty("ZoomY", 2.12)
            elif track == 2:
                ok = it.SetProperty("ZoomX", 0.84) and it.SetProperty("ZoomY", 0.84) and it.SetProperty("Tilt", -88)
            else:
                ok = all(it.SetProperty(k, v) for k, v in face.items())
            bad += 0 if ok else 1
    for rec, label in group["markers"]:
        tl.AddMarker(rec, "Yellow", label, "", 1)
    last = group["infos"][-1]
    want = last["record_frame"] + last["end_frame"] - last["start_frame"]
    got = tl.GetEndFrame() - tl.GetStartFrame()
    print(f"  {name}: {n} segs x3 tracks, {got} frames (expected {want}), failed property sets: {bad}")
    if got != want or bad:
        raise SystemExit(f"{name}: verification failed")


def main():
    groups = json.load(open(sys.argv[1], encoding="utf8"))
    only = set(sys.argv[2:])
    resolve = connect()
    project = resolve.GetProjectManager().GetCurrentProject()
    print("project:", project.GetName())
    pool = project.GetMediaPool()
    for g in groups:
        if only and g["name"] not in only:
            continue
        build(project, pool, g)
    print("save:", resolve.GetProjectManager().SaveProject())


if __name__ == "__main__":
    main()
