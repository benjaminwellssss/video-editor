---
name: music-video-editing
description: Build a music video for a song mashup or remix on this Windows + Ableton + DaVinci Resolve free-edition rig — download source music videos, split stems, measure exact tempo/key, map which source song plays where in the user's mashup, and build a lip-synced, editable Resolve timeline over their Ableton screen recording. Trigger on "mashup", "music video", "stems", "BPM/key of this song", "album art", or a screen recording of an Ableton session. Separate from stream-vod-edit (stream VODs, shorts, captions).
---

# Music Video Editing

Sub-skill for music work — mashups, remixes, music-video visuals. The general
rules in the project `CLAUDE.md` still apply (editable Resolve timeline, never a
flattened render inside the project; read every write back; target timelines by
name). Stream-VOD conventions (captions, censoring, shorts, CLIPS folders) live in
`stream-vod-edit` and do **not** apply here unless asked.

**Keep this work out of the main video-editor setup.** Scripts for this workflow
live in this skill's own `scripts/` folder, not the repo's `scripts/`, and the
main `stream-vod-edit` skill is not edited for music jobs.

## Where things go

`<music-folder>` and `<videos-folder>` are the streaming drive's `Music` and
`Videos` folders (the real locations are in local memory, not in this repo).

| What | Where |
|---|---|
| Downloaded music videos + MP3s | `<music-folder>\` |
| Stems of a source song (Demucs) | `<music-folder>\Stems\<Artist - Song>\{vocals,drums,bass,other}.wav` |
| Album/single covers | `<music-folder>\Album Art\` |
| Large Resolve working media (stretched panels, overlays) | `<videos-folder>\RESOLVE\MM-DD-YYYY_<Name>\` |
| Finished export | `<videos-folder>\EDITS\MM-DD-YYYY_<Name>\` |

Never leave anything in Downloads.

## Tools on this machine

- **yt-dlp**: not installed; run it with `uvx yt-dlp` (uv is on PATH). Search first
  with `--flat-playlist --print "%(id)s | %(title)s | %(channel)s"` on
  `ytsearch4:<query>` and pick the upload from the artist's own channel. Download
  with `-f "bv*+ba/b" --merge-output-format mp4`. Official videos come down as
  AV1/VP9 + Opus — fine for ffmpeg, but re-encode if the user wants to cut the
  originals in Resolve free. MP3: `ffmpeg -vn -c:a libmp3lame -q:a 0`.
- **Demucs**: own venv at `~/.cache/video-editor/demucs-venv` (torch 2.8.0+cu128,
  CUDA works on the NVIDIA GPU). Separate from the WhisperX venv on purpose — don't
  install music packages into that one. Use `-n htdemucs_ft -d cuda --int24` and
  feed it audio pulled from the *video* (Opus source), not the MP3 (second lossy
  copy). ~1 min per song.
- **librosa / soundfile** are in the Demucs venv.
- Album art: the iTunes Search API (`itunes.apple.com/search?entity=album` or
  `lookup?id=<artistId>&entity=album`) gives artwork URLs; swap `100x100bb` for
  `3000x3000bb` for the full-size cover. Downloading needs the user's go-ahead
  (name, source, size).

## Tempo and key

- **Measure tempo exactly, don't trust a beat tracker's headline number.**
  librosa's `beat_track` said 123 BPM for a song that is really 121.00 — enough
  to drift audibly off the grid within ~12 beats in Ableton. Fit a line through
  all beat times of the **drum stem** (onset-refined) and report the slope; check
  each sixth of the song separately to confirm the tempo is steady.
- Key: Krumhansl-Kessler profiles on the harmonic part's mean chroma. A clear
  winner (≥0.8 correlation) is trustworthy; a narrow one (funk/bass-led tracks)
  should be reported as uncertain.
- When asked for a key "in between" two keys, say whether they're already
  compatible (neighbours on the circle of fifths / Camelot) before suggesting a
  shift; transposing more than ~2-3 semitones degrades vocals.

## Ableton help the user has needed

The user runs **Ableton Live 12 Standard** (no built-in stem separation — that's
Suite-only; offer Demucs instead). Things that came up: stems importing at
different lengths = auto-warp guessing a different tempo per clip (fix: clear
warp markers, set Seg. BPM to the measured tempo on all stems together); drifting
off the grid = Seg. BPM slightly wrong; "flex time" = warp markers; Shift-drag a
clip edge in Arrangement to stretch it.

## Mashup → music video pipeline

The user records their Ableton session (screen + mashup audio) and wants the
source music videos synced to it. "Transcribe my Ableton" means: work out which
source song plays where, and from where in the original.

1. **Job folder** under `projects/<job>/` as usual (copy the recording into
   `raw/`). Extract the audio to WAV, find where playback starts
   (`silencedetect`), and split the mashup into stems with Demucs.
2. **Bar-1 time**: read the transport position off a couple of frames of the
   recording for a rough value, then fit the exact beat phase from the mashup's
   drum stem at the project tempo.
3. **Match windows** — `scripts/match_mashup_sources.py <mashup_stems> <bpm>
   <bar1_s> <out.json> NAME=<stems_dir>=<bpm> ...`: half-bar windows, each mashup
   stem against each source song's same stem, the source stretched to the mashup
   tempo, all 12 transpositions tried. The consistent transposition per song tells
   you what the user pitched (on Distort the DCC: DCC −3, DLB +2 → both F♯ minor).
4. **Per-song tracks** — `scripts/mashup_song_tracks.py <raw.json> <bpm> <bar1_s>
   <end_s> <out.json> <mashup_stems> NAME=<bpm>=<stems_dir>=<semitones> ...`: one
   continuous source-position track per song, following its chain and jumping
   only on confident matches; each jump is then placed on the exact beat by
   testing both alignments beat by beat. Sanity check: real jumps land on whole
   bars (a 3-bar skip, an 8-bar repeat). A song the user only muted/unmuted comes
   out as one chain for the whole mashup.
   `scripts/mashup_segments.py` is the alternative "one visual owner at a time"
   view (whoever is singing), for a single-panel edit.
5. **Panels**: pre-stretch each music video to the mashup tempo with ffmpeg
   (`setpts=PTS*<src_bpm>/<mashup_bpm>,fps=<timeline_fps>`) so one panel frame =
   one timeline frame and every cut is a plain trim in Resolve. Render as ProRes
   4444 with alpha, already positioned on a transparent full-frame canvas
   (`format=yuva444p10le,pad=...:color=black@0`) — avoids Resolve Pan/Tilt, whose
   readback isn't trustworthy on this build. Panel source frame for a record
   frame = `round(fps * src_offset / ratio) + rec0 + record_frame`.
   **Gotcha:** `cd dir && ffmpeg ... &` runs the `cd` in the background subshell
   only — the next backgrounded ffmpeg won't see it. Use absolute input paths.
6. **Timeline**: `scripts/build_mashup_clip_infos.py` → clip_infos (V1 recording
   + its audio from bar 1, one track per song panel, optional overlay), then
   `scripts/resolve_build_timeline.py` (adds the video tracks the layout needs).
   Opacity via `timeline_item.set_composite`, read back with `get_composite`.
   Check with `timeline_frame.capture`, then re-set `ExportAudio: true` (capture
   turns it off project-wide).
7. **Frame rate**: set `timelineFrameRate` to the recording's FPS while the
   project has zero timelines; remind the user to set the *playback* frame rate
   by hand.

### Layout the user chose (Distort the DCC, 2026-10-09)

Ableton screen recording full-frame as the background; both music videos as 3:4
portrait panels (750×1000 on 1920×1080), side by side, inside edges 10 px either
side of centre (20 px gap), vertically centred, **75% opacity**. Centre-cropped
from each video (DCC's 2.39:1 letterbox removed first). Song order left→right
follows the title. Handles overlay bottom-right at ~70% in.

## Export

"YouTube settings standard" = Resolve's `YouTube - 1080p` preset, then set
explicitly: mp4/H264, 1920×1080, timeline fps, AAC 48 kHz, `ExportAudio: true`,
`TargetDir` = the dated `EDITS` folder. The preset leaves the codec blank —
always set it. After the render: `render.verify_output`, then `ffprobe
-show_streams` to confirm an audio stream exists.

## Cover art

`scripts/bad_photoshop_cover.py <cover_a> <cover_b> <out.jpg>` — the
deliberately bad "photoshop" mashup cover (sloppy lasso cutout with a white
fringe, a JPEG-crunched rectangle-selected figure, a stretched logo, WordArt
title, Comic Sans credit, lens flare). Its crop/lasso coordinates are specific to
Dead Club City + Give Me The Future; re-pick them for other covers.

## Copyright

Label-owned songs and videos will draw Content ID claims on upload — mention it
once per job, don't lecture. Never write out song lyrics anywhere (reports,
metadata, captions) unless the user supplies them.
