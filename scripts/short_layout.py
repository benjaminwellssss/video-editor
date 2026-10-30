"""The 9:16 shorts layouts. A clip's layout is "layout" in its captions_speakers.json sidecar (missing = cam_top).

cam_top    (default): facecam across the top 658 px, gameplay below over a blurred backdrop.
cam_bottom (alt, 2026-10-26): gameplay across the top 900 px, facecam filling the bottom 1020 px.

Each entry holds where things go on the 1080x1920 frame: the facecam panel auto_zoom works in, the caption anchor,
the default caption-image spot, the handle pop-up centre and the bottom of the who's-talking overlay.
"""

LAYOUTS = {
    "cam_top": dict(panel=(0, 612), caption_y=670, img_top=632, popup=(347, 1036), vo_bottom=572),
    # captions straddle the seam at 900; images sit in the gameplay above them; the pop-up sits between the two
    "cam_bottom": dict(panel=(900, 1020), caption_y=912, img_top=170, popup=(347, 715), vo_bottom=1540),
}


def layout(sidecar):
    name = (sidecar or {}).get("layout") or "cam_top"
    if name not in LAYOUTS:
        raise SystemExit(f"unknown layout {name!r} (have: {', '.join(LAYOUTS)})")
    return LAYOUTS[name]


def video_filter(name, cam, fps):
    """ffmpeg graph from a 1920x1080 stream recording to the 1080x1920 short, ending in [v].
    cam = (w, h, x, y) of the facecam box in the recording."""
    cw, ch, cx, cy = cam
    if name == "cam_top":
        return ("[0:v]split=3[a][b][c];"
                "[a]scale=-2:1920,crop=1080:1920,boxblur=24:2[bg];"
                "[b]scale=2865:1611[g];"
                f"[c]crop={cw}:{ch}:{cx}:{cy},scale=1168:658[f];"
                f"[bg][g]overlay=x=-892:y=311[t];[t][f]overlay=x=-44:y=0,fps={fps},format=yuv420p[v]")
    if name == "cam_bottom":
        # same gameplay scale as cam_top; the cam is scaled to fill 1020 tall and centre-cropped to 1080 wide
        return ("[0:v]split=2[b][c];"
                "[b]scale=2865:1611,crop=1080:900:892:527[g];"
                f"[c]crop={cw}:{ch}:{cx}:{cy},scale=-2:1020,crop=1080:1020:(iw-1080)/2:0[f];"
                f"[g][f]vstack,setsar=1,fps={fps},format=yuv420p[v]")
    raise SystemExit(f"unknown layout {name!r}")


if __name__ == "__main__":
    assert layout({}) is LAYOUTS["cam_top"] and layout({"layout": "cam_bottom"})["panel"] == (900, 1020)
    assert sum(LAYOUTS["cam_bottom"]["panel"]) == 1920
    print("ok")
