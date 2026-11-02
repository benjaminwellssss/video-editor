"""Hype intro for a long-form: a quick-cut montage of N loud/laughing moments over the music bed, each scene swiping in
and SLAMMING (punch-in and shake) on its key word, a stylised colour filter over the lot, then
the handle slamming in over a blurred quiet game moment. Pick the scenes with thumb_caps.moments + a storyboard first; this only renders.

Usage: python hype_intro.py <spec.json>
spec: {"source": master.mp4, "voice": [mic, game], "music": mix.mp3, "music_offset": s (optional: loudest stretch),
       "cam_box": [x, y, w, h], "look": "vhs", "handle": "@name", "font": ttf, "font_size": px, "out": intro.mp4,
       "card": {"at": s, "crop": [x, y, w, h], "blur": sigma},
       "scenes": [{"start": s, "slam": s, "end": s}, ...]}     (source seconds)
Cuts land on the music's beats: each scene's start moves earlier/later so its length is a whole number of beats.
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

from media_info import video_fps

LOOKS = {"vhs": "eq=saturation=1.35:contrast=1.1,rgbashift=rh=-6:bh=6,noise=alls=14:allf=t,"
                "curves=r='0/0.06 1/1':b='0/0.1 1/0.92'"}
SWIPES = ["slideleft", "slideright"]  # whip pans: a slide smeared by a heavy horizontal blur
SR, HOP = 4000, 40           # beat analysis: 10 ms hops
MUSIC_TO_VOICE = 0.6         # music peaks at 60% of the voice's peaks, then ducked under it
HANDLE_S, SWIPE_FRAMES, MIN_LEAD = 1.6, 8, 0.35


def run(cmd):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *cmd], check=True)


def pcm(path, start, dur, sr=SR):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", path,
                          "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def onset(x):
    e = np.log1p(1000 * (x[:len(x) // HOP * HOP].reshape(-1, HOP) ** 2).mean(1))
    return np.maximum(0, np.diff(e, prepend=e[0]))


def loudest_offset(music, win=30.0):
    """Start of the music's punchiest `win` seconds (highest mean onset strength), on a 1 s grid."""
    o = onset(pcm(music, 0, 1e6))
    per_s = o[:len(o) // 100 * 100].reshape(-1, 100).mean(1)
    score = np.convolve(per_s, np.ones(int(win)), "valid")
    return float(np.argmax(score[10:-10]) + 10)


def beat_grid(music, offset, dur):
    """(beat period s, first beat s after offset) by onset autocorrelation, tempo kept within 80-170 BPM."""
    o = onset(pcm(music, offset, dur))
    o = o - o.mean()
    ac = np.correlate(o, o, "full")[len(o) - 1:]
    lo, hi = int(60 / 170 * 100), int(60 / 80 * 100)
    lag = lo + int(np.argmax(ac[lo:hi + 1]))
    if 0 < lag < len(ac) - 1:  # parabolic refine: 10 ms lags drift ~0.1 s over a 10 s intro otherwise
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        lag += 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0
    period = lag / 100
    phases = np.arange(int(lag))
    sums = [o[np.arange(p, len(o), lag).astype(int)].sum() for p in phases]
    return period, phases[int(np.argmax(sums))] / 100


def scene(spec, sc, i, fps, tmp):
    """Full frame up to the slam, then a punch-in with shake (no flash: user 2026-10-26 "looks terrible"): on the full frame (default, user
    2026-10-26: "less facecam more full frame", 1.3x -> 1.04x) or, with spec "slam_on": "cam", cut to the facecam.
    A scene's "cam": true holds the facecam for the lead-in too (when the game is on a menu or loading screen)."""
    s, rel, dur = sc["start"], sc["slam"] - sc["start"], sc["end"] - sc["start"]
    x, y, w, h = spec["cam_box"]
    on_cam = spec.get("slam_on", "frame") == "cam"
    z = "max(1.08,1.35-0.27*on/8)" if on_cam else "max(1.04,1.3-0.26*on/8)"
    shake = "28*max(0,1-on/9)"
    cam = f",crop={w}:{h}:{x}:{y},scale=1920:1080:flags=lanczos"
    lead = cam if sc.get("cam") else ""
    vf = (f"[0:v]split[a][b];[a]trim=0:{rel:.4f},setpts=PTS-STARTPTS{lead},setsar=1[g];"
          f"[b]trim=start={rel:.4f},setpts=PTS-STARTPTS{cam if on_cam else ''},"
          f"zoompan=z='{z}':x='iw/2-iw/zoom/2+{shake}*sin(on*2.7)':y='ih/2-ih/zoom/2+{shake}*cos(on*3.3)'"
          f":d=1:s=1920x1080:fps={fps},setsar=1[f];"
          f"[g][f]concat=n=2:v=1:a=0,fps={fps},format=yuv420p[v];"
          f"[1:a][2:a]amix=inputs=2:normalize=0,alimiter=limit=0.95:level=disabled,atrim=0:{dur:.4f}[m]")
    out = os.path.join(tmp, f"s{i}.mkv")
    cmd = ["-ss", f"{s:.3f}", "-t", f"{dur:.3f}", "-i", spec["source"]]
    for v in spec["voice"]:
        cmd += ["-ss", f"{s:.3f}", "-t", f"{dur:.3f}", "-i", v]
    run(cmd + ["-filter_complex", vf, "-map", "[v]", "-map", "[m]", "-frames:v", str(round(dur * fps)),
               "-c:v", "h264_nvenc", "-cq", "16", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", out])
    return out


def peak(path):
    r = subprocess.run(["ffmpeg", "-nostdin", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(r.stderr.split("max_volume:")[1].split("dB")[0])


def main():
    spec = json.load(open(sys.argv[1], encoding="utf8"))
    fps = video_fps(spec["source"])
    d = SWIPE_FRAMES / fps
    off = spec.get("music_offset")
    off = loudest_offset(spec["music"]) if off is None else off
    period, first = beat_grid(spec["music"], off, 30)
    off += first  # intro t=0 is on a beat
    print(f"music {off:.2f}s, {60 / period:.1f} BPM")
    scenes = []
    for sc in spec["scenes"]:  # whole beats per scene; each one but the last also carries its swipe overlap
        beats = max(2, round((sc["end"] - sc["start"]) / period))
        start = sc["end"] - beats * period - d
        assert sc["slam"] - start >= MIN_LEAD, f"scene at {sc['slam']}: slam too close to the start"
        scenes.append({**sc, "start": start})
    scenes[-1]["start"] += d
    with tempfile.TemporaryDirectory() as tmp:
        files = [scene(spec, sc, i, fps, tmp) for i, sc in enumerate(scenes)]
        lens = [sc["end"] - sc["start"] for sc in scenes]
        # swipes: xfade chain, offsets = running length minus the overlaps so far
        ins = sum((["-i", f] for f in files), [])
        g, t, last_v, last_a = [], 0.0, "0:v", "0:a"
        for i in range(1, len(files)):
            t += lens[i - 1] - d
            g.append(f"[{last_v}][{i}:v]xfade=transition={SWIPES[(i - 1) % len(SWIPES)]}:duration={d:.4f}"
                     f":offset={t:.4f},gblur=sigma=60:sigmaV=0.5:enable='between(t,{t - 2 / fps:.4f},{t + d + 2 / fps:.4f})'[v{i}]")
            g.append(f"[{last_a}][{i}:a]acrossfade=d={d:.4f}[a{i}]")
            last_v, last_a = f"v{i}", f"a{i}"
        mont = os.path.join(tmp, "montage.mkv")
        g.append(f"[{last_v}]{LOOKS[spec['look']]},format=yuv420p[look]")  # montage only: the handle card keeps the game's own colours
        run(ins + ["-filter_complex", ";".join(g), "-map", "[look]", "-map", f"[{last_a}]",
                   "-c:v", "h264_nvenc", "-cq", "16", "-c:a", "pcm_s16le", mont])
        mont_s = t + lens[-1]
        # handle: slams from huge to size in 0.12 s, over a quiet game moment cropped clear of
        # the facecam and blurred (spec "card": {"at": s, "crop": [x, y, w, h], "blur": sigma})
        font = spec["font"].replace("\\", "/").replace(":", "\\:")
        c, size = spec["card"], spec.get("font_size", 150)
        cx, cy, cw, ch = c["crop"]
        card = os.path.join(tmp, "card.mkv")
        run(["-ss", f"{c['at']:.3f}", "-t", f"{HANDLE_S}", "-i", spec["source"], "-f", "lavfi", "-i",
             f"anullsrc=r=48000:cl=stereo", "-filter_complex",
             f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale=1920:1080,setsar=1,gblur=sigma={c['blur']},"
             f"eq=brightness=-0.08:saturation=0.8,drawtext=fontfile='{font}':text='{spec['handle']}':fontcolor=white:"
             f"fontsize='if(lt(t,0.12),{size * 2.6:.0f}-{size * 13:.0f}*t,{size})':x=(w-tw)/2:y=(h-th)/2:"
             # the overlay hub's Beachday look: navy outline and hard navy drop shadow
             f"borderw={max(2, size // 28)}:bordercolor=0x0a1020:shadowcolor=0x0a1020:"
             f"shadowx={max(3, size // 14)}:shadowy={max(3, size // 14)},fps={fps},"
             "format=yuv420p[v]", "-map", "[v]", "-map", "1:a",
             "-t", f"{HANDLE_S}", "-frames:v", str(round(HANDLE_S * fps)), "-c:v", "h264_nvenc", "-cq", "16", "-c:a", "pcm_s16le", card])
        joined = os.path.join(tmp, "joined.mkv")
        run(["-i", mont, "-i", card, "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "h264_nvenc", "-cq", "16", "-c:a", "pcm_s16le", joined])
        total = mont_s + HANDLE_S
        if spec.get("music_mix") is False:  # voices only: the user lays his own music under it in Resolve (10-30)
            run(["-i", joined, "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", spec["out"]])
        else:
            mix_music(spec, joined, mont, mont_s, off, total, tmp)
    got = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                spec["out"]], capture_output=True, text=True).stdout)
    assert abs(got - total) < 0.2, (got, total)
    print(f"{spec['out']}: {got:.2f}s ({len(scenes)} scenes, {mont_s:.2f}s montage + {HANDLE_S}s handle)")


def mix_music(spec, joined, mont, mont_s, off, total, tmp):
    """Music bed loud, ducked under the voice, hits the handle slam then fades."""
    mus = os.path.join(tmp, "music.wav")
    run(["-ss", f"{off:.3f}", "-t", f"{total:.3f}", "-i", spec["music"], "-ar", "48000", "-ac", "2", mus])
    gain = peak(mont) + 20 * np.log10(MUSIC_TO_VOICE) - peak(mus)
    run(["-i", joined, "-i", mus, "-filter_complex",
         "[0:a]asplit[vo][key];"
         f"[1:a]volume={gain:.2f}dB,afade=t=out:st={mont_s + 0.15:.3f}:d=0.9[mu];"
         f"[mu][key]sidechaincompress=threshold=0.05:ratio=6:attack=5:release=250[duck];"
         f"[vo][duck]amix=inputs=2:normalize=0,alimiter=limit=0.95:level=disabled[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", spec["out"]])


if __name__ == "__main__":
    main()
