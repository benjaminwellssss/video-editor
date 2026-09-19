# Video Editor Pipeline

Raw talking-head footage → transcript → cut decision list → real trimmable
Resolve timeline → motion graphics on a second track → manual finish/export.

Never flatten a cut into a single rendered MP4. The deliverable is always an
editable Resolve timeline.

## Flow

1. **Intake**: copy the raw clip into `projects/<job>/raw/`. Never move or
   touch the original.
2. **Transcribe**: WhisperX with word-level timestamps, once per video, cached
   at `projects/<job>/transcript/words.json`.
3. **Cut**: read the transcript, decide what stays, write
   `projects/<job>/transcript/cuts.json`. Show the cut list before building.
4. **Replay into Resolve**: rebuild the cut as separate trimmable clips on a
   real timeline via `create_timeline_from_clips`. Never use `apply_cuts` —
   it deletes whole items and reports success while doing it.
5. **Graphics**: HyperFrames compositions, rendered as transparent ProRes 4444
   overlays, imported onto a second video track. Show the graphics plan
   before building.
6. **Finish**: user finishes and exports manually in Resolve.

## Job naming

`projects/<job>/` is named after the video's content, short kebab-case
(`morning-routine-breakdown`). Never named after the camera file, a date, or a
pipeline stage.

## Environment notes (this machine)

- **Windows, NVIDIA GPU present.** WhisperX runs CUDA float16 via the venv at
  `~/.cache/video-editor/whisperx-venv` (`Scripts/python.exe`, not
  `bin/python`). PyPI torch is CPU-only on Windows — the CUDA build was
  installed explicitly from `https://download.pytorch.org/whl/cu128`. If CUDA
  errors at load or mid-run, fall back to CPU int8 and keep going — never
  block a transcription on a GPU stack problem.
- **DaVinci Resolve: free edition.** External scripting is gated to Studio, so
  this project uses the in-app bridge (`DAVINCI_RESOLVE_BRIDGE=1` in
  `.mcp.json`). The bridge must be running inside Resolve
  (Workspace → Scripts → resolve_bridge) for the MCP to reach it — same
  requirement as the "External scripting = Local" preference on Studio.
  Resolve must be restarted after the bridge install so it re-scans the
  Scripts folder, and a project must be open (Scripts menu is empty in
  Project Manager).
- **PYTHONUTF8=1** must be set for every script that pipes output — piped
  Python defaults to cp1252 on Windows and a stray ✓/→ glyph in a status line
  will crash an otherwise-working run.
- **Shell**: Git Bash (POSIX sh), not PowerShell, for pipeline scripts. Windows
  installs go through `winget`; Python is `python`, not `python3`.
- **PATH caching gotcha**: a Claude Code session's shell inherits PATH at
  session start. Installing something via winget mid-session (ffmpeg, uv)
  does not become visible to that session's Bash calls until Claude Code
  itself restarts. Locate the tool's actual install dir under
  `AppData\Local\Microsoft\WinGet\Packages\...` and prefix PATH inline in the
  meantime.
- **iPhone .MOV frame rate trap**: ffprobe reports 30000/1001 (29.97) but
  Resolve ingests the same clip at a flat 30.00. After importing to the media
  pool, read the clip's `FPS` property via the API and treat that as the
  authority for the project frame rate and all seconds-to-frames math — not
  the ffprobe value. If every clip's duration reads back off by a uniform
  1.001 factor, the frame-rate model is wrong: delete and rebuild the project
  at the right rate, don't nudge individual frames.
- Timeline frame rate and Playback frame rate are two separate settings in
  Project Settings → Master Settings. The scripting API cannot write the
  playback one — this is a manual step for the user. Mismatch causes chopped,
  glitchy audio that looks like a broken export but is a project setting.
- `create_timeline_from_clips` frames are **source** frames at the raw's frame
  rate, not timeline frames. `end_frame` is exclusive. `record_frame` is
  timeline-relative and reads back with a `01:00:00:00` offset.
- Target Resolve timelines by name, never "current timeline" — the user
  switches timelines while a script is running. Read every property write
  back; a reported success is not proof.
- HyperFrames version is pinned in render scripts, not left floating to
  `latest`.

## Repo layout

- `vendor/davinci-resolve-mcp/` — Resolve MCP server (cloned, do not edit)
- `vendor/hyperframes/` — HyperFrames engine (cloned, do not edit)
- `.claude/skills/` — HyperFrames composition-authoring skills, copied from
  `vendor/hyperframes/skills/`
- `.mcp.json` — Resolve MCP registration for this project
- `assets/` — permanent branding/assets (never leave these in Downloads):
  `fonts/` (Bebas Neue, used by captions) and
  `overlays/handles_overlay.gif`, the user's animated social-handles overlay.
  **It goes in most, if not all, of the user's videos** (decided 2026-09-19) —
  default to including it; details and placement in the `stream-vod-edit`
  skill ("Social-handles GIF overlay").
- `projects/<job>/{raw,transcript,graphics,outputs}/`
