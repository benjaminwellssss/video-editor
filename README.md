# video-editor

A personal pipeline for turning raw talking-head / stream footage into
finished, captioned deliverables — driven end-to-end through Claude Code.

Raw footage → transcript → cut decision list → a real, trimmable DaVinci
Resolve timeline → motion-graphics overlays → manual finish/export. The
pipeline never flattens a cut into a single rendered file; the timeline
stays editable in Resolve all the way to the end.

## Flow

1. **Intake** — copy the raw clip into `projects/<job>/raw/`.
2. **Transcribe** — WhisperX with word-level timestamps (CUDA float16, falls
   back to CPU int8), cached at `projects/<job>/transcript/words.json`.
3. **Cut** — read the transcript, decide what stays, write
   `projects/<job>/transcript/cuts.json`.
4. **Replay into Resolve** — rebuild the cut as separate trimmable clips on a
   real timeline via the DaVinci Resolve MCP's `create_timeline_from_clips`.
5. **Graphics** — HyperFrames compositions rendered as transparent ProRes 4444
   overlays, imported onto a second video track.
6. **Finish** — manual finish and export in Resolve.

Full operational detail (environment quirks, frame-rate traps, audio-track
identification, censoring rules, shorts-cutting conventions) lives in
[`CLAUDE.md`](CLAUDE.md) and [`.claude/skills/stream-vod-edit`](.claude/skills/stream-vod-edit) —
that's the authoritative reference this repo is built to be driven by.

## Repo layout

- `scripts/` — standalone Python/ffmpeg tooling: caption rendering and
  note-driven effects (`render_captions.py`, `caption_fx.py`), jump-cut short
  builders, speaker-colored caption cards, SRT builders, handle/watermark
  overlays, caption-timing verification.
- `.claude/skills/` — Claude Code skills for this pipeline, including
  `stream-vod-edit` (the VOD → highlight-reel → shorts workflow) and a set of
  HyperFrames motion-graphics authoring skills.
- `vendor/` — cloned third-party dependencies (DaVinci Resolve MCP server,
  HyperFrames engine) — not edited here, not tracked in git.
- `assets/fonts/` — caption typefaces (Bebas Neue).
- `projects/<job>/{raw,transcript,graphics,outputs}/` — per-job working
  directories (raw footage and rendered outputs are git-ignored; only the
  pipeline code is tracked).

## Captions

`render_captions.py` renders animated, word-level pop-in captions as a
transparent overlay from a `captions.json` card list (produced by a
companion caption editor). Per-card editor **notes** written in plain English
drive effects via `caption_fx.py` — grow/zoom, shake/vibrate, dance, glow,
color, intensity words (*gentle* → *violent*/*max*), image/gif overlays with
a placement grid, cross-card ramps ("progressively more intense"), a
find-and-apply-everywhere mode ("make all instances of 'X' do a shake"), and
a persisting text-position toggle (e.g. "near the bottom" / "under my face"
for a full-facecam segment, "centered again" to return to normal). A note
the renderer doesn't understand is never silently dropped — it's reported so
a human can handle it.

## Environment

Windows, NVIDIA GPU. DaVinci Resolve **free edition** — external scripting
is Studio-only, so this repo talks to Resolve through its in-app bridge
script instead. See `CLAUDE.md` for the full list of machine-specific quirks
(frame-rate handling, PATH caching after a mid-session install, the bridge
launch sequence, etc.) before running anything here on a different machine.
