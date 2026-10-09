"""clip_infos for a side-by-side mashup timeline, from mashup_song_tracks.py output.

Track 1 is the screen recording (video + its mashup audio) from bar 1 to the end.
Each song gets its own video track of panel clips: the song's music video
pre-stretched to the mashup tempo (one frame of panel media = one timeline frame),
cut wherever the song jumps in the arrangement. An optional overlay layer goes on
the track above at a fraction of the way through.

usage: build_mashup_clip_infos.py <song_tracks.json> <out.json> <fps> <bar1_s> <end_s>
           REC=<clip_id> NAME=<clip_id>=<bpm>=<track> ... [OVERLAY=<clip_id>=<frames>=<track>=<at_fraction>]
Clip ids can be placeholders and substituted once the media is imported.
"""
import json
import sys


def main():
    tracks = json.load(open(sys.argv[1]))
    out, fps, bar1, end_s = sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
    rec0 = round(bar1 * fps)                 # recording frame shown at timeline frame 0
    total = round(end_s * fps) - rec0        # timeline length in frames
    mbpm = None
    infos, songs, overlay = [], {}, None
    for a in sys.argv[6:]:
        key, val = a.split("=", 1)
        if key == "REC":
            infos.append({"clip_id": val, "start_frame": rec0, "end_frame": rec0 + total,
                          "record_frame": 0, "track_index": 1})
        elif key == "MBPM":
            mbpm = float(val)
        elif key == "OVERLAY":
            cid, frames, track, at = val.split("=")
            overlay = (cid, int(frames), int(track), float(at))
        else:
            cid, bpm, track = val.split("=")
            songs[key] = (cid, float(bpm), int(track))

    for name, (cid, bpm, track) in songs.items():
        ratio = mbpm / bpm
        segs = tracks[name]
        for i, s in enumerate(segs):
            rf_s = max(0, round((s["start"] - bar1) * fps))
            rf_e = total if i == len(segs) - 1 else round((s["end"] - bar1) * fps)
            if rf_e <= rf_s:
                continue
            # panel media time = source time / ratio = offset/ratio + recording time
            src_s = round((s["src_offset"] / ratio) * fps) + rec0 + rf_s
            infos.append({"clip_id": cid, "start_frame": src_s, "end_frame": src_s + (rf_e - rf_s),
                          "record_frame": rf_s, "track_index": track, "song": name})

    if overlay:
        cid, frames, track, at = overlay
        infos.append({"clip_id": cid, "start_frame": 0, "end_frame": frames,
                      "record_frame": round(total * at), "track_index": track})

    json.dump(infos, open(out, "w"), indent=1)
    for ci in infos:
        print(f"V{ci['track_index']} {ci['clip_id']:8} rec {ci['record_frame']:5}-{ci['record_frame'] + ci['end_frame'] - ci['start_frame']:5}  src {ci['start_frame']:5}-{ci['end_frame']:5}")
    print(f"timeline: {total} frames = {total / fps:.2f}s")


if __name__ == "__main__":
    main()
