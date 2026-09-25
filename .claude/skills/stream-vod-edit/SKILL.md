---
name: stream-vod-edit
description: Edit a local Twitch/streaming VOD into a full cleaned VOD, a 20-40 min highlight edit, and vertical 9:16 shorts with animated captions, on this specific Windows + DaVinci Resolve free-edition + WhisperX pipeline. Trigger on "edit this VOD/stream", "cut a highlight reel", "make shorts from this stream", or any request touching E:\Streaming\Videos. Covers file destinations/naming, caption styling, audio-track selection, and censoring rules learned the hard way on this rig.
---

# Stream VOD Edit

This skill encodes the working conventions for turning a raw Twitch/stream
recording into finished deliverables on this machine. It exists because this
specific setup (DaVinci Resolve **free edition**, no Studio license) is missing
several APIs a normal pipeline would use — see "Resolve free-edition
limitations" below — and because getting the audio track wrong once already
cost a full rebuild of a 6-hour project. Read this whole file before starting
a new VOD job.

## Non-negotiables

1. **Never guess the audio track.** Ask first (see "Audio track
   identification").
2. **Never flatten the main cut into a single rendered file inside Resolve's
   own project.** Build it as a real, trimmable timeline via
   `create_timeline_from_clips`. Never use `apply_cuts` — on this install it
   deletes whole items while reporting success.
3. **Nothing large lives permanently on `C:`.** `C:` is the SSD — fine as a
   scratch/working drive mid-job — but every deliverable ends on `E:`. Delete
   or don't create large intermediates on `C:` once the job's outputs are on
   `E:`.
4. **Don't ask "should I proceed" once the brief is set.** Work through cuts,
   censoring, and shorts without stopping. The exceptions are the audio-track
   confirmation above and anything genuinely destructive to existing work.
4a. **After resuming from any session interruption (the user closing and
   reopening the session, a crash, etc.), re-verify every file a background
   job was writing when it happened — file existence and a plausible size
   are not enough.** A background ffmpeg job killed mid-write leaves a file
   that looks complete (right extension, multi-megabyte, even a "task
   completed" notification from the harness, since that only reports the
   wrapper script's own exit code) but has no moov atom and is unplayable.
   This has happened twice on this project in one session — once to a
   composited short, once to a rendered caption overlay — both looked fine
   until `ffprobe -show_entries format=duration` was actually run against
   them. Re-run that check on anything touched right before the
   interruption before treating it as done.
5. **Verification frames/audio samples (extracted with `ffmpeg -frames:v 1`
   to spot-check a layout, caption, or audio track) are scratch, not
   deliverables.** Write them to the session's scratchpad temp directory,
   not the project root — this project's root accumulated ~40 loose
   `chk*.png` / `scratch_*.png` / `*_check.m4a` files over one job and had
   to be swept clean. If a verification file needs to persist briefly for
   the user to see, send it with `SendUserFile` rather than leaving it on
   disk at the project root.

## Pre-build checklist (before touching `create_timeline_from_clips` on any new job)

Run these in order, every time, before building the main cut. Each one has
independently cost a full rebuild when skipped — doing them upfront is
cheaper than diagnosing the symptom later.

1. **Frame rate**: compare the media pool clip's real `FPS`
   (`media_pool_item.get_clip_property`) against
   `project_settings.get_setting("timelineFrameRate")`. Must match before
   building anything — see "Resolve free-edition limitations" below for the
   two failure modes and the fix.
2. **Audio track**: confirmed with the user per "Audio track identification"
   below — never guess.
3. **Long-edit scope, in one round**: ask (or infer from what's already been
   told) the selection criteria (funny highlights vs. "interesting"
   progress/discovery) *and* the length ceiling *and* whether shorts are
   wanted, together, before cutting anything — not as separate follow-ups
   after a first attempt turns out to be the wrong shape. Default assumption
   absent other instruction: curated funny highlights, ceiling 20-40 min
   (see "Respect a stated length as a ceiling" below) — but a session with
   little banter may warrant asking instead of assuming.
4. **Structure plan**: identify the real spoken intro and outro in the
   transcript, and pick a cold-open moment, *before* building — see
   "Structure & hook convention" below. Finding these after a timeline is
   already built means rebuilding it; finding them first means one build.
5. **Large `clip_infos` builds** (roughly 50+ entries): use
   `scripts/resolve_build_timeline.py <clip_infos.json> "<timeline name>"
   [if_exists]` instead of the MCP tool's inline `clip_infos` parameter —
   it drives the same `CreateEmptyTimeline`+`AppendToTimeline` calls directly
   over the bridge from a JSON file, so a 261-entry (or 900+-entry) cut list
   never has to be pasted into the conversation. Keep using the MCP tool
   directly for small builds (shorts, a handful of clips) where the inline
   form is simpler.

## File destinations

Everything lives under `E:\Streaming\Videos\`, which has four subfolders:

| Subfolder | Contents |
|---|---|
| `VOD` | The full-length recording after cleanup (dead air trimmed, forbidden-word scenes cut, "fuck"/slurs excised) — still the whole stream, not a highlight reel. |
| `EDITS` | The curated 20-40 min highlight edit (or whatever length the user asks for — treat a stated length as a ceiling, not a target: "at longest 40 min" means deliver *up to* 40, not pad to it). |
| `CLIPS` | All vertical 9:16 short-form outputs, captioned. |
| `RESOLVE` | Resolve project backups/exports and any Resolve-specific working files (not raw footage). |

**Folder-per-batch rule:** for every job, create one new dated folder in
*each* subfolder you touch (not just `CLIPS`) — e.g. a VOD edit pass creates
`E:\Streaming\Videos\VOD\09-09-2026_Valheim\`, the highlight reel creates the
matching folder under `EDITS`, and the shorts batch creates it under `CLIPS`.

**Inside a `CLIPS` batch folder, confirmed 2026-09-18: every short gets its
own subfolder**, named after the clip (`lord_ass_king/`, not a
`short_lord_ass_king.mp4` file sitting flat next to a dozen others). That
folder holds the clip's full deliverable set together:

```
CLIPS/09-17-2026_Valheim/lord_ass_king/
  lord_ass_king.mp4
  captions.json       <- the caption cards.json used for this render
  metadata.txt
```

**Captions are always delivered as `captions.json` inside that clip's
folder**, not left behind only in the working `projects/<job>/shorts/`
tree — this is what lets `scripts/caption_editor/` (or a future re-render)
find the right cards file for a given delivered clip without hunting
through scratch files by name prefix.

**A duplicate/variation of a short (different caption treatment, a
different cut, etc.) gets its own subfolder inside the clip's folder,
named for what changed** — not a filename suffix like `_v2` or `_colored`
sitting flat next to the original:

```
CLIPS/09-17-2026_Valheim/lord_ass_king/
  lord_ass_king.mp4
  captions.json
  metadata.txt
  speaker-colored-captions/
    lord_ass_king.mp4
    captions.json
    metadata.txt
```

`VOD`/`EDITS` batches are usually a single file and don't need this
per-item nesting — this rule is specifically for `CLIPS`, where a batch is
several independent shorts (and sometimes several variants of one short).

**Naming format:** `MM-DD-YYYY_GAME` (or `MM-DD-YYYY_EVENTNAME` for a non-game
stream), using the date the content was *recorded*, not the edit date. If a
second distinct batch lands on the same date+game (a second editing pass, a
different highlight cut, etc.), disambiguate with a trailing number:
`MM-DD-YYYY_GAME_2`, `_3`, ... Don't number the first/only batch.

Working/scratch files (raw transcripts, intermediate ffmpeg renders, caption
card JSON) stay under the project's own `projects/<job>/` tree per
`CLAUDE.md` — those are not deliverables and don't need the `E:\Streaming`
naming convention, but keep them off `C:` too once they're multi-GB (see
Non-negotiable 3).

## Audio track identification

**Ask before building anything that depends on which track is whose voice.**
On at least one rig here, a multi-track OBS recording had two tracks
(different indices) that looked like separate speaker feeds but were actually
near-duplicate full-program mixes — summing them caused phase-cancellation
garble, and even after fixing that, the "main speaker" track picked
algorithmically turned out not to be the streamer at all. Both mistakes were
expensive (hours of rework across a full VOD + 5 shorts).

The reliable process:

1. Probe every audio track/channel with a **short transcription sample** at
   2-3 different timestamps spread across the recording (not just one) —
   silence at one timestamp doesn't mean the track is empty everywhere.
2. Compare transcripts across tracks. If two tracks produce near-identical
   text, they're the same program mix, not separate speakers — don't try to
   isolate a speaker by picking one of them.
3. Cut a **10-second audio-only sample** from a candidate track and send it
   to the user before committing to it project-wide. Repeat with a second
   sample from a different scene if the first doesn't get a clear "yes."
4. Only after explicit user confirmation, use that track as *the* audio
   source for every deliverable (VOD, EDITS, CLIPS). Don't remix or blend
   tracks unless the user asks for that — a single correctly-identified track
   is simpler and more reliable than an amix on this setup.
5. If the user later says a labeled speaker is wrong, stop all audio work
   immediately and wait for them to check manually — don't keep guessing.

### This rig's specific 4-track layout (confirmed 2026-09-16/17)

Once identified for a given rig, a track layout is a standing fact about the
hardware/software setup, not a one-off finding — reuse it on the next VOD
from the same rig without re-probing from scratch (a light re-verification
is still fine, a full multi-timestamp probe is not needed every time).
Confirmed layout on this streamer's setup, using **VLC's 1-based track
numbering** (ffmpeg's `-map 0:a:N` is 0-based, so VLC track K = ffmpeg
index K-1):

| VLC track | ffmpeg index | Content |
|---|---|---|
| 1 | 0 | **Aggregate** — full program mix: game audio, the streamer's voice, music, and any other players' voices (Discord/co-op partners) all mixed together. |
| 2 | 1 | **Streamer's isolated voice only** — clean single mic, but misses every other speaker entirely. |
| 3 | 2 | Labeled "Discord" but in practice carries a near-duplicate of the full program mix when a co-op partner is present, not a clean isolated feed of them — confirmed silent on a solo-stream night, confirmed near-identical to the aggregate track on a co-op night. Not useful as a clean second-speaker source. |
| 4 | 3 | Game/music only, no speech. |

**Standing rule, confirmed 2026-09-18: transcribe from the aggregate track
(VLC 1 / ffmpeg index 0) by default, always** — not the isolated voice
track. Using the isolated voice track for transcription was tried once and
caused two compounding bugs on a co-op session: (1) every caption/SRT was
missing the other player's dialogue entirely, since that track only ever
captures the streamer, and (2) far worse, the **dead-air trim silently cut
real content** — any stretch where the streamer was quiet while the other
player was talking read as silence on the isolated track and got trimmed
out of the edit, even though it wasn't dead air at all. Re-cutting from the
aggregate track after the fact roughly **doubled** the kept duration of a
124-minute session (66 min → 124 min) purely by recovering wrongly-trimmed
co-op dialogue — this is not a minor caption gap, it silently reshapes the
whole cut.

**Only fall back to the isolated voice track when the streamer's own lines
are too quiet/unclear in the aggregate mix** to transcribe accurately for a
specific stretch — cross-check that narrow window against the isolated
track rather than switching the whole job's source over.

There is no clean isolated track for a second speaker on this rig. Full
per-speaker color-coded captions would require diarization on the aggregate
mix (see the "Multi-speaker captions" section under Captions below), which
is far too slow to run casually — the pragmatic default is a single
merged-speaker transcript from the aggregate track (whoever's talking gets
captioned, no color differentiation), not full diarization, unless the user
explicitly asks for the diarized treatment and is told the time cost upfront.

## Video editing

- **Transcribe once** with WhisperX (word-level timestamps), cached per job.
- **Cut by transcript gaps**, not amplitude-based silence detection, for
  dead-air removal — trim to a ~1s buffer around speech, don't delete the gap
  entirely (leaves natural breathing room).
- **Non-destructive always**: the main cut and the full-VOD cleanup are both
  built via `create_timeline_from_clips` with explicit `clip_infos`
  (start/end/record frame lists), saved to `transcript/*.json` in the job
  folder so the exact cut can be rebuilt against a different audio source
  later without re-deciding the edit. This is what saved the audio-track
  rework in practice — the cut decisions and the source clip were decoupled.
- When rebuilding a timeline against a corrected source, use
  `if_exists="version"` so the previous version is preserved, never
  overwritten in place.
- **Prioritize humor for highlight/short selection *by default* — but check
  what the user actually asked for this job, since it varies.** A session
  that's mostly base-building/world-progress (not much banter) may get an
  explicit ask for an "interesting" long edit instead of a "funny" one —
  in that case, select for build/world-visual progress, discoveries, and
  mechanically significant moments (boss fights, near-deaths, a base
  reaching a visually striking state) rather than joke density, and say so
  when reporting back so it's clear the selection criteria changed for this
  job. The separate short-form clips can still default to funny-only
  regardless of what the long edit is optimizing for — a job can ask for
  "an interesting long edit, plus grab funny shorts if any exist" as two
  different selection criteria in one request.
- Mark funny beats with a yellow timeline marker, boss-fights/set-pieces
  with cyan, as you go — regardless of which selection criteria the edit
  itself is using.
- **Respect a stated length as a ceiling.** "30-40 min edit" or "at longest
  40 min" means stop cutting once you're in that window with the best
  material — don't pad weaker material in to hit the top of the range.
- **Fade in/out**: this Resolve build has no working keyframe API, so build
  fades as a sequence of very short (1-2 frame) clips with stepped static
  `Composite Opacity` values instead of an animated keyframe curve.
- **Vertical shorts (9:16)**: Resolve free edition won't reliably render a
  second video track under a custom-resolution timeline (confirmed dead on
  this install), so shorts are composited with **ffmpeg**, not inside
  Resolve: facecam cropped to the top third, gameplay cropped/scaled to the
  bottom two-thirds. Verify the facecam's on-screen position per clip via a
  direct ffmpeg frame extraction before compositing — it isn't guaranteed
  constant across a long VOD, and a Resolve-rendered "reference" frame isn't
  trustworthy enough to check it (rendering is itself unreliable here).
- **4-5 shorts per batch** (unless told otherwise), 30-90s each, funniest
  self-contained moments — see "Selecting moments to clip" below for how
  candidates are found.
- **YouTube Shorts max length is 3 minutes (180s)**, extended from 60s in
  October 2024 — confirmed via web search 2026-09-18, don't assume the old
  60s ceiling. This is headroom, not a target: don't pad a short to fill it,
  but don't reflexively cut a punchline down to under a minute either if the
  setup genuinely needs more room.
- **A punchline needs its setup, even if the setup runs long.** Confirmed
  2026-09-18 after a batch of shorts came back too short/disjointed: several
  had the punchline cut with barely any lead-in (e.g. jumping straight to
  "My lord, my lord ass king, what is thy bidding today?" with no context),
  when the actual joke only works with the setup that precedes it — in that
  case, a whole preceding riff ("I am asking. I am asking. I am asking.")
  that the punchline is a pun on ("ass king" ⟵ "asking"). Cutting tight to
  just the marked/flagged moment optimizes for the wrong thing here. Before
  finalizing a short's boundaries, read backward from the punchline through
  the actual transcript (not just the marker timestamp) and find where the
  *joke* — not just the *line* — starts; that's often 30-90+ seconds earlier
  than the flagged moment, sometimes bleeding into an adjacent bit that
  should be merged in rather than treated as a separate short (two markers
  ~2 minutes apart turned out to be one continuous bit and got combined into
  a single longer short instead of two disjointed short ones).
- **Jump cut dead time inside a short.** A short does not have to be one
  unbroken slice of the raw timeline — if nobody's talking or nothing
  interesting is happening partway through an otherwise-good moment, cut
  that dead stretch out and jump straight to where it picks back up, the
  same way the main-cut dead-air trim works, just applied *inside* a single
  short instead of across the whole VOD. Shorts should feel **fast,
  addicting, and exciting** — dead air reads as boring and works against
  that. Rules for the cut itself:
  - Never cut into the middle of a word or let two words collide at the
    splice (no audio overlap at the join).
  - Leave a small buffer of natural air on either side of the cut — about
    **0.5-1 second** — rather than a hard zero-gap splice; it should feel
    like a snappy edit, not a glitch.
  - This means a short is built as a **concatenation of multiple kept
    segments** from the raw source (trim each segment, then concat video and
    audio), not a single continuous `-ss`/`-t` extraction. Word-level
    timestamps for captions have to be **remapped into the new, shorter
    timeline** afterward (cumulative kept-duration-so-far + offset into the
    current segment) — captions built against the original continuous
    timestamps will drift out of sync the moment a cut removes any time.
  - **Composite each kept segment as its own ffmpeg call, then concat the
    finished clips — don't build one giant `filter_complex` that trims every
    segment, concats the raw video, and *then* composites the
    facecam/gameplay layout in a single graph.** The all-in-one-graph
    version reliably failed on this machine with `Cannot allocate memory`
    partway through filtering (reproduced even on a small 4-segment/23s
    clip run by itself, so it isn't just parallel-job contention) — and
    worse, it can fail *silently*: one run reported success but the output's
    video stream had only 4 frames total while the audio track was the full
    correct length. **Always check `ffprobe -show_entries
    stream=nb_frames,duration` on a jump-cut output before trusting it built
    correctly** — a job exiting 0 is not enough here. The fix: run the
    facecam/gameplay composite separately per kept segment (small filter
    graph, low memory, one segment's worth of `-ss`/`-t` on the input), then
    stitch the already-composited, same-format clips together with the
    concat *demuxer* (`ffmpeg -f concat -i list.txt -c copy`) — a stream
    copy, not a filter, so it's cheap and doesn't reintroduce the memory
    problem. `scripts/build_jumpcut_short.py` implements this pattern.
- **Selecting moments to clip**: going forward, the user marks candidate
  moments live with an **OBS marker** while streaming — check for those
  markers first and prioritize clipping around them. Absent markers (e.g. an
  older recording with none), fall back to scanning the transcript for
  funny moments directly (laughter cues, punchlines, chat reacting strongly,
  running bits) the way this pipeline has been doing.
  **Confirmed working end-to-end 2026-09-15** (test file
  `2026-09-15 14-37-42.mp4`, OBS Studio 32.2.2): OBS's "Add Chapter Marker"
  hotkey writes real MP4 chapter atoms directly into the recording — no
  sidecar file, no separate export step. Read them with
  `ffprobe -v error -show_chapters -of json <file>`; each shows up as
  `{"start_time", "tags": {"title"}}`. The very first chapter is always
  titled **"Start"** at `start_time: 0` and is auto-added by OBS at
  recording start — it is not a user mark, skip it. Unnamed marks come back
  as "Unnamed 1", "Unnamed 2", etc. in press order; if the user names a
  marker live, that name lands in `title` instead. **How to apply:** for
  any new VOD, run the ffprobe chapter check first, before falling back to
  transcript scanning. **A marker's timestamp is *after* the funny moment,
  not its center** — the user hits the hotkey as a reaction once they
  realize something clip-worthy just happened, not in anticipation of it, so
  by the time the marker lands the moment itself is already in the past.
  Confirmed 2026-09-24: read the transcript window from roughly **60 seconds
  before** the marker's timestamp (not centered on it, and not looking
  after), find where the actual bit starts within that window, and clip
  from there.
  **Marker naming = category.** The user's markers are for **funny moment
  edits** (short-form candidates) — treat a marker's `title` as its category
  label when present. For now that means every non-"Start" chapter is a
  funny-moment/shorts candidate by default (whether left as "Unnamed N" or
  named), since that's the only category in use. If the user starts naming
  markers something else on stream (e.g. a distinct tag for a main-cut
  highlight, a boss-fight/set-piece beat, etc.), treat that as a new
  category rather than assuming every marker still means "funny moment" —
  ask if it's ambiguous which bucket a newly-seen marker name belongs to.
- **Always present the candidate list before building any shorts — don't
  spend compute/render time on picks the user hasn't seen.** Confirmed as
  the right process after a batch of 6 shorts built blind (no candidate
  review first) mostly missed the mark ("almost none of the ones you
  selected earlier were good enough to use") — a second pass that listed 10
  candidates with actual quoted lines and approximate timestamps *before*
  compositing anything got a clean per-item yes/no back, at zero wasted
  render cost on the rejected ones. This is a narrow, intentional exception
  to non-negotiable #4 ("don't ask should I proceed") — it's not a
  stop-and-ask-permission gate, it's a cheap list-then-build checkpoint
  specifically for shorts selection, same spirit as CLAUDE.md's "show the
  cut list before building" for the main cut.
  **How to apply:** For every batch of shorts, first list each candidate as
  a short quoted excerpt (not a vague description — the actual funny line)
  with its approximate raw-timestamp range and a one-line reason it's
  self-contained, then wait for the user to accept/reject/swap individual
  items by number before touching ffmpeg. Flag borderline-content picks
  (innuendo, edgy topics short of the cut-scene tiers in
  [[feedback-content-moderation]]) explicitly in the list so the user can
  drop them without having to ask why. Only build the ones actually
  approved.
- **Shorts are conditional on being funny enough — not every job wants
  shorts by default.** When the job is "grab 3-5 clips if there are any
  funny moments," it's fine to come back with fewer than 3 (or zero) if the
  material genuinely isn't there, rather than stretching weak moments to
  hit a quota. Apply the full caption + handle overlay treatment only to
  the ones that clear the bar.
- **Full-screen facecam takeover for a direct-to-camera moment.** When the
  subject is looking straight at the camera and talking/reacting to the
  audience (not the game), that beat can cut to a full-screen facecam shot
  instead of the normal split layout — crop tighter on the same webcam box
  to fill the whole 1080x1920 frame, hold for the moment, then hard-cut back
  to the split layout. Implemented as `"layout": "facecam_full"` on a
  segment in `build_jumpcut_short.py` — carve it out as its **own short
  segment** (split → facecam_full → split, three segments at the
  surrounding source timestamps) rather than trying to animate a
  transition; a hard cut in and out is what was actually asked for
  ("hold it for a beat before cutting back"). The crop this needs is
  necessarily tight and upscaled a lot (the source webcam box is only
  460x342, so a 9:16 slice out of it is ~192x342 blown up ~5.6x to fill
  1080x1920) — expect some softness, there's no higher-res facecam source
  to draw on. Re-derive the crop's x-offset if the subject isn't
  horizontally centered in their own webcam box.

### Vertical short layout: facecam/gameplay split (current, corrected)

- **Background/wall bleeding in at the facecam's far-left edge.** The
  *original*, untouched source crop (`460:342` at `1460,738` — the webcam
  box exactly as OBS composited it, flush against the source's right/bottom
  edges) is clean at every timestamp checked. The bleed only appeared after
  a "fix" attempt *enlarged* that crop by ~5% to give more headroom —
  extending further left pushed the sampled region past the webcam box's
  real edge into contaminated territory. **The actual fix: use the
  original, natural crop as-is — don't enlarge past it, don't shrink below
  it either** (shrinking clears the bleed too, but produces a visibly
  tighter/more-zoomed framing than the user's own reference style calls
  for). After any change here, spot-check the face stays in frame for **at
  least 80% of the clip's duration**.

- **A visible black bar between the facecam and gameplay halves — root
  cause was NOT a compositing bug at all, despite two rounds of "fixes"
  aimed at the compositing step.** The raw recording has a **~22px solid
  black letterbox bar baked into the very top row of the source video**
  (y=0 to ~21, full width, confirmed via direct pixel inspection at
  multiple x-columns — this is an OBS output-resolution artifact, not
  anything downstream). The gameplay crop's source rectangle started at
  y=0, so it was including that black band as the first ~22 rows of the
  gameplay layer — which sits directly under the facecam, so it read as a
  gap at the seam. **Fix: start the gameplay crop at y=24 (skipping the
  bar plus a small safety margin), not y=0.**
  - Two earlier fix attempts targeted the wrong layer entirely and did not
    work, despite each looking plausible on paper: first, overlapping the
    facecam/gameplay overlay coordinates by ~20px (reasoning: "the two
    regions must not be meeting exactly"); second, switching from
    coordinate-based `overlay` compositing to `vstack` (reasoning: "pure
    pixel concatenation can't have a gap by construction" — true, and it
    still didn't fix it, which is what proved the bug wasn't in the
    compositing step at all). **A visible verification frame after each of
    those two attempts still showed the gap** — that's what eventually
    forced tracing it back to the raw source instead of the compositing
    math. When a fix doesn't visibly work, stop iterating on the same
    layer/step and check the *input* to that step instead.
  - How this was actually found: crop a generously-sized, brightened
    (`eq=brightness=0.4`) strip of the seam region from a rendered frame
    and look at it directly — pixel-value scans down a single column can
    be misleading here since real gameplay footage is often genuinely dark
    (a mining/cave scene reads as near-black at some x-columns even with
    zero bug), so a solid black column reading doesn't by itself prove a
    gap. Cropping a wide brightened strip and eyeballing it made the
    letterbox band's perfectly uniform, full-width flatness obvious against
    real (textured, lit) gameplay content immediately below it.

Concrete filter chain (facecam source region at its natural, unmodified
size; gameplay crop skips the source's own top letterbox bar; `vstack` used
for the actual composite — simpler than overlay+background now that the
real cause is fixed, and structurally can't reintroduce a coordinate-based
gap):

```
[0:v]crop=911:1056:504:24,scale=1080:1260[gameplay];
[0:v]crop=460:342:1460:738,scale=1080:803,crop=1080:660:0:71[facecam];
[facecam][gameplay]vstack=inputs=2[outv]
```

**Always verify with an actual extracted, brightened frame strip after
changing any of these numbers, at more than one timestamp** — arithmetic
that "should" work, and even a structurally-gap-proof filter like `vstack`,
both failed to catch this because the bug was never where either fix was
looking. Don't trust reasoning about the compositing step alone here; pull
a frame, brighten it, and look at the seam directly.

These exact numbers are specific to this facecam's on-screen box and this
recording setup's letterbox offset — re-derive them (source crop
position/size, split y-value, letterbox band height) per new OBS layout
rather than assuming they're universal, per the
facecam-position-isn't-guaranteed-constant note above.

### Facecam framing in the split layout (user's decision, 2026-09-22)

**Never stretch the facecam to force-fill its share of the vertical
frame.** The old approach scaled the *entire* facecam capture box
(background wall, mic arm, window chrome and all) up to exactly the
canvas width — that's "prioritizing the frame of the facecam" and it's
no longer the goal. Instead:

1. **Crop *within* the facecam box**, tighter than the full capture
   region — a proper close-up on the subject (head/shoulders), not the
   whole webcam window. Verify by frame extraction same as always, at
   more than one timestamp.
2. **Scale that tighter crop up preserving its native aspect ratio** —
   width and height scale by the same factor. No forced-fit distortion,
   ever.
3. Because the scaled result is narrower than the canvas, **pad it out
   to full canvas width with plain black** (`pad=<canvas_w>:<h>:<x>:0:black`,
   centered) rather than stretching to fill. A sliver of gameplay showing
   through on the sides instead of black is also fine if that's a better
   fit for a given layout — the constraint is "never distort the face,"
   not "always black."

Worked example (`valheim-deadweight-challenge`, facecam box was
`465:405` at `1455,675`): tight crop `crop=280:330:1595:715` (cuts the
window chrome and most of the background clutter), scaled 2x to
`560:660` (exact aspect preserved), padded to `1080:660:260:0:black`.
`facecam_height` for the gameplay-overlay math becomes the padded box's
own height (660 here), not some larger number chosen to match the old
full-bleed style.

### Handle/watermark overlay

A static `@beanjahmean` handle sits in the empty headroom space above the
facecam subject's head, for every short. Same font as captions (Bebas Neue),
white fill with black stroke, but **50% of the caption font size** (75pt vs
150pt) and a lighter stroke (~4px vs 7px) to match. Rendered once as a
transparent PNG (`scripts/render_handle.py`) and composited on top of the
caption overlay for the short's full duration — it doesn't move or animate.

**Left-aligned, not top-centered** — a top-centered handle gets covered by
an iPhone's "Dynamic Island" (or any other front-camera cutout) when a
viewer watches fullscreen, since that sits horizontally centered at the very
top of the physical screen. Left (or right) corners are clear of that on
every device regardless of the exact vertical safe-zone height, which is
what actually fixed it — bumping the *centered* text down by some guessed
offset would still be device/app-dependent. Current position: `LEFT_X=45,
TOP_Y=55` in `render_handle.py`.

The caption anchor (top line centered on "the black divider bar") should be
re-centered on the new seam y-value (the overlay y used for gameplay) even
though there's no visible black bar to anchor to anymore — it's still the
natural visual boundary between the two halves.

### Social-handles GIF overlay (standing branding element)

The user supplied an animated overlay for their social handles (a retro
"find-me.exe" window: @beanjahmean, "same handle, every platform", Twitch /
X / Instagram / TikTok / YouTube buttons) and asked on 2026-09-19 that it go
in **most, if not all, of their videos from now on** — treat it as the
default for every short and edit unless the user says to leave it off, and
mention it when reporting a finished video so a missing one is noticed.

- **Where video overlays live (user's decision, 2026-09-19):**
  `E:\Streaming\Overlays + Images\Video Overlays\` — not in this repo. Look
  there first for any overlay; when the user adds a new one, that's where it
  belongs. Never leave it (or any asset a Resolve project links to) in
  Downloads: moving a linked file takes the media offline, so after moving
  one, relink it with `media_pool_item.replace_clip` and read `File Path`
  back. (`hooded_figure_audio` was relinked to the E: path.)
- **Files there** — all five are 880x540, 25fps, 8.04s, with alpha, and
  settle into the *same* resting pose (the window centered in its canvas);
  they differ only in the entrance animation:
  - `handles_overlay.gif` — the original; window slides up in from the bottom
  - `handles_overlay_left.gif` / `_right.gif` / `_top.gif` — slides in from
    that side
  - `handles_overlay_pop.gif` — scales/pops in
  (Entrances identified from frames at 0.3s; the user didn't say which they
  prefer — use the original by default and offer the others, e.g. when the
  overlay would collide with something on that edge.)
- **Current default placement for shorts (user's decision, 2026-09-22):
  middle-right, 75% scale, using the `_right` (slides in from the right)
  variant, resting so it doesn't cover captions.** Superseding the older
  bottom-center default below for 9:16 shorts specifically. Concretely, on
  a 1080x1920 canvas: scale the GIF's own 880-wide canvas to 660 wide
  (75%, height follows at 405 - never change width/height independently,
  the source has no alpha-safe way to re-derive a mismatched aspect), then
  overlay at `x=1080-w-24` (right edge, small margin) and `y=1600-h/2`
  (vertically centered on the middle of the frame's bottom third, i.e.
  `y=1600` for a 1920-tall canvas - recompute proportionally for a
  different canvas height). Verify by frame extraction same as
  always - both the resting frame and an early (~0.5s in) frame to confirm
  the slide-in reads as coming from off-screen right, and that it clears
  whatever's rendering at the caption anchor height.
- **Older reference placement (from `hooded_figure`, 09-16, now superseded
  for shorts by the above):** on video track 2, ZoomX/ZoomY 0.7, Pan 0,
  bottom-center of the 1080x1920 frame (window occupies roughly x 220-860,
  y 1608-1920, bottom edge slightly clipped — the API's Tilt readback of
  about -2379 is not trustworthy on this build, so copy placement by
  looking at a rendered frame, not by the number). It plays once for its
  full 8.04s, starting roughly 70% of the way into the short. Still the
  starting point for anything that isn't a 9:16 short (e.g. 16:9 long-form
  needs its own placement — ask or propose one and show a frame).
- **It is separate from the static `@beanjahmean` handle** (top-left,
  `render_handle.py`), which stays on every short as before — both were
  composited together on `hooded_figure` and the user was fine with that.
  The GIF is the animated call-to-action; the static handle is the
  persistent watermark. If the user ever wants one dropped, ask which.
- **Track 2 rendered fine here.** On a project created at the right
  1080x1920/30fps *before the first timeline existed*, a GIF on V2 rendered
  correctly in Resolve's own export — this contradicts the older "second
  video track never renders" finding for custom-resolution timelines, so
  don't assume either way: **render, pull a frame from inside the GIF's
  window with `ffmpeg -ss`, and look at it.** If it ever fails to render,
  overlay the GIF with ffmpeg instead (`-i handles_overlay.gif`, overlay
  with `enable='between(t,T0,T0+8.04)'`), and verify by frame extraction.
- The stream's own OBS overlay also contains a small "find-me.exe" window
  (bottom-right of the source) that the vertical gameplay crop clips at the
  frame edge — that is in the raw footage, not something the pipeline
  added.

### `caption_fx.py` note vocabulary (2026-09-22)

Beyond the original grow/zoom/shake/vibrate + intensity words, editor notes
(`*like this*` in the caption editor, stored as `card["note"]`) also support:

- **A color word** (red/green/blue/yellow/orange/purple/pink/white/black/
  cyan) overrides that card's text fill, on top of any motion effect —
  "red font, ANGRY SHAKING" gets both.
- **glow/shine/holy/neon/radiant/halo** — a brief radiant flash behind the
  text (rises over 0.12s, fades across the rest of the card). Uses the
  note's color if one's also given, else a warm gold-white.
- **dance/bounce/groove/wiggle** — a smooth vertical bob, distinct from
  shake's jitter.
- **A ramp across several cards**: a note containing progressively/
  gradually/increasingly ramps its effect linearly across itself and every
  contiguous following card that shares the same effect key, peaking at
  whatever's the strongest intensity word anywhere in that run (add
  "maximum"/"max" to a later card to set the peak explicitly).
- **"make all instances of "X, Y" do a &lt;effect&gt;"** (or "every/
  whenever/any time it says") — applies that effect to every card in the
  lane whose text is one of the named words, anywhere in the timeline, not
  just cards after the instruction.
- **A bare URL** in a note requests an image/gif overlaid near the caption.
  render_captions.py never fetches it itself (downloading from an external
  site needs explicit go-ahead first) — it looks for the file already
  cached at `<shorts-dir>/note_images/<sha1-of-url-16>.{png,gif,jpg,jpeg,
  webp}` and skips with a printed path if it isn't there yet. "until the
  end (of the video)" makes it persist to the short's end, otherwise it
  shows for 3s from the card's start; "above"/"over" vs "under"/"below"/
  "beneath" picks which side of the caption bar it sits on (default below).
  To actually include one: download the image (with the user's go-ahead,
  since it's an external fetch), save it to that path, and re-render.

All of the above is still subject to the "note with nothing recognised ->
NOT UNDERSTOOD, reported, never silently dropped" rule.

### Captions after the user hand-edits a short in Resolve

Sometimes the user takes a finished short into Resolve to tweak audio/music
and trims dead air. The edit then no longer matches the caption timing built
against the base clip, so the captions must be re-timed, not reused:

1. Read the cut from Resolve, never guess it: `timeline.source_range_report`
   gives the kept **source frame ranges** (end exclusive) per clip; also list
   every track's items (`timeline.get_items_in_track`) to see what they added
   (music on A2, the GIF on V2).
2. **Take word text and timing from the full-VOD transcript, cut to the
   short's source windows — do NOT transcribe the short clip on its own.**
   Learned the hard way on `hooded_figure` (2026-09-19): a clip-only
   WhisperX run has no audio around the clip's edges, so it swallowed an
   entire opening phrase ("THE HECK IS THAT"), stretched a word across 1.3s
   of silence, and parked a stray "I" 0.6s early. The full-VOD words (which
   have context) were right, agreeing with the isolated mic. Use diarization
   only for *who* is speaking, never as the word/timing source.
3. `scripts/build_cards_from_ranges.py <words.json> <cards.json> <fps>
   <start:end> ...` (it wants whisperx-format words with a `speaker` field —
   build that from the full-VOD words mapped onto the base timeline)
   drops words inside removed stretches, shifts the rest onto the edited
   timeline, and applies speaker colors (heaviest speaker green).
   **Always run `scripts/verify_caption_timing.py <cards.json> <voice.wav>
   [fps ranges]` on captions the pipeline just generated** (never on ones the
   user has hand-edited — see "manual edits are gospel" below) against the
   isolated-mic audio cut the same way; it flags PHANTOM (a card with no voice under it — e.g. Whisper's
   invented trailing "you"), EARLY (a card up long before its word) and LONG
   (one word held >1s, i.e. swallowed neighbours). It flagged a phantom "YOU"
   in an already-delivered short. Fix what it flags before rendering.
4. Render captions for the exact export duration, then composite with the
   handle PNG over the **Resolve export** and copy its audio (`-c:a copy`).
   Verify the export first: `render.verify_output`, then `ffprobe` for an
   audio stream, then compare durations against the timeline frame count.
5. When the user wants to mix music themselves, give them a music-free base
   (stream audio only) and let them add the track; check their export's audio
   by comparing it against the stream audio (the music zone should differ,
   untouched stretches should match to ~-30 dB).
6. File it as a variant folder per the CLIPS rules above.

### Caption editor notes and effects (`*note*`, `|`)

The user edits captions in their standalone editor (`E:\Coding Repos\
caption-editor\`, launched from the "Caption Editor" desktop shortcut). In a
caption's text box (2026-09-19):

- `*like this*` is an **editor note**: an instruction, never displayed. The
  editor saves it in the card's `"note"` field and keeps it out of `"lines"`.
  Treat every `note` in a `captions.json` as a to-do from the user for that
  card, and say in your report what you did with each.
- `|` is a **line break** (`HECK|YES` -> two stacked lines; `"lines"` has two
  entries).

`render_captions.py` runs each card's note through `scripts/caption_fx.py`,
which understands grow / zoom / shake / vibrate plus intensity words (gentle,
very, extremely, violent...), and prints for every note what it inferred, or
`NOT UNDERSTOOD` — a note it can't do is reported, never silently dropped, so
handle those by hand (or extend `caption_fx.py`). A card may also carry an
explicit `"fx"` dict, which wins. Effects apply to that card's caption only,
never to the video. The renderer also strips any `*...*` still sitting inside
`lines` (older files), so a note can never be drawn.

**Simultaneous captions (`"lane"`, added 2026-09-19):** the editor has a
timeline panel with a lane per row (start with one, "🕒+ Timeline" adds more;
captions can be dragged in time and between lanes, bumped with the arrow keys).
Each card saves a `"lane"` (0-based, omitted for lane 0). `render_captions.py`
draws lane 0 as the big main caption on the seam and every further lane
smaller, stacked underneath, so several speakers can be on screen at once;
per-card `fill` (speaker color), `note` effects and `emphasis_scale` work on
every lane. A lane showing alone anchors to the seam. This is the layout to
use when the user says two people are talking over each other — put each
speaker on their own lane rather than trying to interleave them.

**Overlapping cards** (within one lane): the newest-started card wins and the
older one never comes back (the same rule as the editor's preview). This matters because a
word held long by the aligner overlaps its neighbours, and hand-edited
timings can too — check overlaps in a user's file before assuming a card
will show. Untagged cards (no `speaker`/`fill`) render white; don't guess
speakers for the user.

**The user's manual caption edits are gospel — render them exactly as
written, and do not audit them.** (Stated by the user 2026-09-19 after I ran
several rounds of audio/transcript cross-checks on their hand-edited
`lord_ass_king` captions and then asked them questions about their timings.)
If a `captions.json` has been edited by hand — text, emoji, timing, speaker
tags, notes, merged or deleted cards — apply it as-is: don't compare it to a
transcript, don't run `verify_caption_timing.py` on it, don't "correct" or
question its timings, don't ask them to confirm choices that look odd. The
only thing to do with an odd-looking edit is render it. (In that very case
the user's timings turned out right and the transcript wrong, but the rule
holds even when you can't prove that.) The verification tools above are for
captions *the pipeline generated*, where nobody has yet listened and decided.
The one allowed exception is mechanical: a renderer behaviour that would make
the render differ from what the user saw in the editor preview (e.g. overlapping
cards) gets fixed in the renderer, in the user's favour, silently.

### This machine's ffmpeg build: two silent-failure gotchas (found 2026-09-21)

The installed ffmpeg (`gyan.dev` full_build, built with `--disable-w32threads`)
has two real bugs that don't announce themselves as errors — both were found
building shorts for the 09-19 stream, and both are now fixed in
`build_custom_crop_short.py` and `build_jumpcut_short.py`, but watch for
either symptom in any *new* ffmpeg filter graph on this machine:

- **`vstack` fed by two crop+scale branches of the same input segfaults.**
  Reproduced down to a minimal case (matching widths, a 5s clip, a shallow
  seek) — not a scale-mismatch or large-file-seek problem, and not fixed by
  an explicit `split` filter instead of implicitly referencing `[0:v]` twice,
  or by forcing `-threads 1`. `overlay` onto a black canvas with the exact
  same crop/scale filters works fine and is what both short-builder scripts
  use now (`color=...[bg];[bg][facecam]overlay=0:0[tmp];[tmp][gameplay]overlay=0:<seam_y>[outv]`).
  A `subprocess.run(..., check=True)` call surfaces this as a normal-looking
  `CalledProcessError` with exit code 3221226356 (0xC0000005) on Windows —
  recognize that exit code as this bug, not a memory/OOM issue.
- **`color=c=...:s=WxH:d=N` with no `:r=` defaults to 25fps**, and because it
  was the first input in the filter graph, the whole composited output
  silently became 25fps even though the source is 30fps — `ffprobe`'s
  `duration` field still read correct (frames-so-far / stated-fps happens to
  work out), so this only shows up by checking `r_frame_rate`/`avg_frame_rate`
  directly, not by checking duration alone. **Always pass `:r=30` (or
  whatever the project's actual rate is) on every `color=` source**, and
  spot-check `ffprobe -select_streams v:0 -show_entries
  stream=r_frame_rate` on a freshly-built short before trusting it — a
  quiet frame-rate downgrade like this will desync anything timed
  separately (a caption overlay rendered at the correct 30fps, for one).

### Resolve free-edition limitations (why ffmpeg does so much of this)

- No audio-volume API at all (`SetProperty('Volume', ...)` always returns
  `False`) — can't mute or balance in-timeline. Censoring is done by
  **excising the frame range**, never by muting.
- No timeline split/razor primitive.
- Per-timeline resolution override exists but a brand-new timeline doesn't
  inherit a custom vertical resolution automatically — set it explicitly.
- `Crop*` properties get silently rewritten under a custom-resolution
  timeline (not a clean scale factor) — don't trust a crop value you didn't
  just re-read back.
- `.srt` import via the scripting API fails silently — the user has to
  import captions manually in-app.
- A second (or higher) video track does not reliably render under a
  custom-resolution (vertical) timeline on this install — confirmed dead via
  extreme `Transform` values and `set_clip_enabled(false)` producing zero
  visual difference in the render despite the property read-back being
  correct. This is *why* vertical shorts are composited in ffmpeg instead of
  as a second track inside Resolve.
- **A new/existing project's `timelineFrameRate` can silently be 24 while the
  source footage is 30fps.** **Check this before building anything, as the
  literal first step of any new job**: read the clip's real FPS via
  `media_pool_item.get_clip_property`, then immediately compare against
  `project_settings.get_setting("timelineFrameRate")`. Don't wait to
  discover this from a bad render or a gap-riddled timeline — it's a 10-
  second check that has cost multiple full timeline rebuilds when skipped.
  - **Two distinct failure signatures have been observed from the same root
    cause, and which one you get is not predictable in advance**: (a) the
    frame count reads back correct via `get_end_frame`/`get_start_frame` (no
    drift shown at the API level) but the rendered file plays at the wrong
    real-world duration — a 24-vs-30 mismatch inflates it by exactly 1.25x
    (confirmed via `render.verify_output`'s `duration_ratio`), slow-motion
    video with detuned/slowed audio; **or** (b) `AppendToTimeline` silently
    truncates every clip to exactly 24/30 (0.8x, floor-rounded) of its
    requested length and stitches a gap into the remainder — confirmed via
    `timeline.detect_gaps_overlaps` showing hundreds of gaps whose durations
    exactly equal each clip's `designed_length - floor(designed_length*0.8)`.
    Signature (b) is worse because the *content* is wrong (missing frames,
    not just mistimed), and the top-level `get_end_frame`/`get_start_frame`
    duration can land close to the intended total by coincidence (gaps
    roughly backfilling the truncated frames), which makes it look
    deceptively close to correct unless you specifically check
    `detect_gaps_overlaps` or the per-item durations from
    `timeline.get_items_in_track`. **Either way, the fix is the same: don't
    try to diagnose the symptom, just check `timelineFrameRate` vs the
    clip's real `FPS` before building, full stop.**
  - **The fix: `project_settings.set_setting("timelineFrameRate", "30")`
    DOES work via the API — but only while the project has zero timelines.**
    Confirmed both ways on this rig: it silently fails (`success: false`,
    and `probe_project_settings` reports `write: false`) on a project that
    already has timelines/clips in it, but succeeds cleanly (readback
    confirms) on a brand-new project before anything's been added — check
    `timeline.list` returns `[]` first. If the project already has
    timelines, there is no known API fix — confirmed again 2026-09-16, three
    separate `set_setting` attempts (string "30", int 30, "30.000") all
    returned `success: false` on a project with existing timelines. A
    Resolve GUI attempt to change it may also refuse/grey out once media
    exists, so the reliable path is asking the user to open a fresh,
    still-empty project (Project Manager → new project, don't open/import
    anything into it yet) and setting the rate there before any timeline is
    built. **Don't spend more than one retry on `set_setting` once a project
    has timelines — it does not work, go straight to asking for a fresh
    project instead of re-trying value formats.**
  - `timelinePlaybackFrameRate` is a **separate, genuinely unwritable**
    setting — `SetSetting` returns `False` for every value/type tried,
    before or after a timeline exists (this is a known upstream limitation,
    not specific to this project). It doesn't affect export correctness the
    way `timelineFrameRate` does, so don't block on it; if the user wants it
    matched too they have to do it by hand in Project Settings.
  - A quick throwaway single-clip timeline test is NOT a reliable way to
    detect the frame-count-drift symptom ahead of time — a 1-clip/30-frame
    test on one affected project showed Resolve silently conforming 30
    source frames down to a 24-frame timeline span, which is *different*
    behavior from a full multi-clip build (which kept all frames 1:1 and
    just tagged/exported them at the wrong rate). Checking the raw
    `timelineFrameRate` setting directly, on a fresh empty project, is the
    fast and reliable move — do it as the very first step of any new job,
    right after import, before building any cut.

## DaVinci Resolve: connection & linking process (full detail)

This is the complete, step-by-step account of how this machine's Claude ↔
Resolve link works, and exactly how to diagnose it when it breaks — which it
has, more than once, mid-job. Read this before assuming Resolve is
unreachable for any reason other than what's listed here.

### Why it isn't a normal connection

DaVinci Resolve's **external** scripting API (the thing a plain Python
script outside Resolve would use) is gated to **Studio** — this machine runs
the **free edition**, so that path is closed. The workaround this project
uses is an **in-app bridge**: a script that runs *inside* Resolve's own
Python interpreter (via `Workspace > Scripts`), opens a local TCP listener,
and answers requests from the MCP server running outside Resolve. The MCP
server is configured to *only* try this bridge transport, never the (closed)
external path.

### The moving pieces, in order

1. **`.mcp.json`** (project root) registers the MCP server:
   ```json
   {
     "mcpServers": {
       "davinci-resolve": {
         "command": "C:\\Users\\Bem\\Desktop\\video-editor\\vendor\\davinci-resolve-mcp\\venv\\Scripts\\python.exe",
         "args": ["C:\\Users\\Bem\\Desktop\\video-editor\\vendor\\davinci-resolve-mcp\\src\\server.py"],
         "env": {
           "RESOLVE_SCRIPT_API": "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting",
           "RESOLVE_SCRIPT_LIB": "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\fusionscript.dll",
           "PYTHONPATH": "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules",
           "PYTHONHOME": "C:\\Program Files\\WindowsApps\\PythonSoftwareFoundation.Python.3.13_3.13.3824.0_x64__qbz5n2kfra8p0",
           "DAVINCI_RESOLVE_BRIDGE": "1"
         }
       }
     }
   }
   ```
   `DAVINCI_RESOLVE_BRIDGE=1` is what forces bridge-only mode — without it
   the server would try (and fail) the Studio-only external path first. The
   other four env vars point at Resolve's own scripting SDK and the specific
   embedded Python runtime Resolve ships, which the MCP server's venv needs
   on its path to even import the `DaVinciResolveScript` module.
2. **The bridge script must be started by hand, inside Resolve, every time
   Resolve (re)starts.** It does not auto-start. In Resolve:
   `Workspace > Scripts > resolve_bridge`. That menu is populated from
   Resolve's Scripts folder and is **empty if no project is open** — open the
   project first, then check the menu.
3. **The bridge call blocks.** `resolve_bridge` is not a fire-and-forget
   script — once launched it opens a listener and sits there; the Scripts
   menu invocation that started it does not return. That's expected and
   correct. On this machine it shows up as a **`fuscript.exe`** child process
   of `Resolve.exe`.
4. **Connection config**: `C:\Users\Bem\.config\davinci-resolve-mcp\bridge.json`
   holds `host` (`127.0.0.1`), `port` (seen as `49632` on this machine, but
   don't hardcode it — always read this file), an auth `token`, and
   `allowed_media_roots` / `allowed_output_roots` path allowlists the bridge
   enforces server-side. This file is written once and persists across
   Resolve restarts; only the live listener behind it needs re-starting.

### Diagnosing "bridge unavailable"

Work through these in order — don't jump straight to "restart everything."

1. **Call any lightweight tool** (e.g. `timeline.list`) and actually read the
   error's `remediation` field — the MCP server's error envelope is
   self-documenting and names the exact fix for the common cases.
2. **A slow (~60s) timeout vs a fast (~2s) refusal are different signals.**
   A slow timeout usually means nothing is listening yet or the port is
   firewalled/unreachable. A fast refusal (`WinError 10061`, "actively
   refused") means something *was* listening very recently but isn't now, or
   two things are fighting over the port (see next point) — check again
   immediately, the state can flap.
3. **Check for two `Resolve.exe` processes.** This is the single most common
   cause on this machine: a Resolve window from an earlier session never
   fully closed, and a second one gets launched alongside it. Both may try to
   bind the bridge's port, and ownership will flap between them from one
   check to the next. Diagnose with PowerShell:
   ```powershell
   Get-Process -Name "Resolve","fuscript" -ErrorAction SilentlyContinue |
     Select-Object Id,ProcessName,StartTime | Sort-Object StartTime
   Get-NetTCPConnection -LocalPort 49632 -ErrorAction SilentlyContinue |
     Select-Object LocalAddress,LocalPort,State,OwningProcess
   ```
   Two `Resolve.exe` rows with very different `StartTime` values is the
   tell. **The fix is to fully quit the OLD instance** (the one with the
   earlier `StartTime`), not to launch a third one or restart the new one —
   once only the fresh instance remains, re-run `resolve_bridge` from its
   Scripts menu and retest.
4. **Why a plain `getppid()` orphan-check can't catch this on Windows**: the
   bridge's own source (`resolve_bridge.py`) documents that Windows does not
   reparent orphaned processes the way POSIX does, so a stale bridge can
   outlive the Resolve that launched it, keep holding the port, and answer
   with a dead handle — "every surface-level check passes" while the client
   still sees a timeout. This is a known, documented failure mode (referenced
   in-source as issue #112), which is exactly why step 3's *process list*,
   not just a port/socket check, is the reliable diagnostic.
5. **For a more detailed error than the MCP tool surfaces**, call the bridge
   client directly instead of going through the MCP layer:
   ```bash
   cd vendor/davinci-resolve-mcp
   DAVINCI_RESOLVE_BRIDGE=1 ./venv/Scripts/python.exe -c "
   import sys; sys.path.insert(0, 'src')
   from utils import resolve_bridge_client as bc
   try:
       proxy = bc.connect(timeout=8)
       print('CONNECTED:', proxy.GetProjectManager())
   except Exception as e:
       print(type(e).__name__, e)
   "
   ```
   This surfaces the raw socket exception (e.g. the exact `WinError`) instead
   of the MCP layer's summarized message.
6. **Never suggest restarting Claude Code itself to fix this.** The
   connectivity problem lives entirely on the Resolve/bridge side; this
   client hasn't changed. Restarting the coding session loses all
   conversation context and fixes nothing — only Resolve (and, if needed,
   the bridge script within it) needs restarting.
7. There's also a standalone diagnostic, `scripts/resolve_bridge_probe.py`,
   that reports whether the current Scripts-menu execution model is
   `child_process` or `in-process` — but it's only meaningful **run from
   inside Resolve's own Scripts menu**. Running it externally (plain
   `python.exe scripts/resolve_bridge_probe.py`) just reports "no resolve
   object," which confirms nothing beyond "this was run outside Resolve."

### Version pin

This project pins Resolve to **21.0.4.5**. Resolve **21.1** moved Python
scripting behind Studio for the free edition and no longer lists `.py`
scripts in the Scripts menu at all — on 21.1+, a bridge-unavailable error may
be final and unfixable rather than a transient connection issue. If a
Resolve auto-update ever lands on 21.1+, that's a different problem than
anything in the "Diagnosing" list above.

### Working inside the project once connected

- **Bin structure**: the "Master" bin (root) holds raw source clips, cleaned
  single-track audio sources, and the "current" working timelines. An
  "Archive" bin holds prior finalized/archived versions and short-form
  intermediate clips. `folder.get_clips()` / `get_subfolders()` operate on
  the **current** folder if no `path` is given — and the current folder is
  *not* always root. Call `media_pool.get_current_folder()` first, or always
  pass an explicit `path` (e.g. `"Master"`), rather than assuming.
- **Target timelines/clips by name or id, never "current timeline."** The
  user switches timelines in the UI while a script may still be running.
- **`create_timeline_from_clips` frame semantics**: `start_frame`/`end_frame`
  are **source** frames at the raw clip's own frame rate, `end_frame` is
  **exclusive**, and `record_frame` is timeline-relative but reads back with
  a baked-in `01:00:00:00` offset (108000 frames at 30fps) — a timeline that
  looks like it ends at frame 163110 with cuts that only go up to
  record_frame 55110 is not a bug, it's that offset.
- **Rebuilding non-destructively**: pass `if_exists="version"` to
  `create_timeline_from_clips` when replacing a timeline (e.g. after fixing
  the audio source) — it auto-suffixes the name (`"Main Cut"` →
  `"Main Cut v02"`) and leaves every prior version untouched. This is the
  standard way to redo a cut against a corrected source without losing the
  original.
- **Bringing a new file into the project**: `media_storage.import_to_pool
  (items=[path])` imports into whatever folder is currently set as current —
  set the folder first.
- **Before reusing a saved `clip_infos` payload against a different source
  clip** (e.g. swapping in a corrected audio file while keeping the exact
  same cut), verify the new clip is **frame-identical** to the old one via
  `media_pool_item.get_clip_property` on both (`FPS`, `Duration`, `Frames`,
  `Video Codec`, `Audio Ch`) — only safe to reuse the same start/end/record
  frame numbers 1:1 if all of those match exactly. This is what makes the
  "keep the cut decisions, swap the audio source" trick from "Video editing"
  above actually safe.
- `media_pool_item` also exposes a `replace_clip(clip_id, path)` action that
  relinks an existing media pool item's file in place, keeping its id. This
  was considered but **intentionally not used** for a source swap on an
  already-named clip (e.g. one named `..._mixed.mp4`) — relinking in place
  leaves a clip whose name no longer describes its actual content, which is
  a silent trap for later confusion. Prefer importing the new file as its
  own clip and rebuilding the timeline (`if_exists="version"`) against its
  own id instead, even though it's more steps.

## Captions

Applies to the vertical shorts (and the main cut/VOD if the user asks for
burned-in or soft captions there too). Current spec, confirmed by the user:

> **Known issue: caption timing runs slightly late.** WhisperX word timestamps
> as used so far have produced captions that land a touch after the word is
> actually spoken, which reads as laggy/off-sync. **Captions must appear
> either exactly on, or slightly *before*, the true start of the word —
> never after.** When building the card timeline, pull each card's start
> time earlier by a small fixed lead (start checking around 80-150ms and
> verify against the actual composited video, not just the transcript JSON,
> since the error is in the perceived sync, not necessarily the raw
> timestamp). Confirm sync by scrubbing the composited output next to the
> audio waveform, not by trusting the transcript numbers alone.
>
> **The early lead is a small fine-tune, not seconds.** A word must never be
> on screen 1-2+ seconds before it's actually said — that reads as a
> different, worse bug (captions racing ahead of the audio) than the
> late-timing issue this lead is meant to fix. If a card's start time is
> ever computed from something other than that specific word's own
> timestamp (e.g. inherited from a previous card's end, a merged/queued
> group, or a default fallback), double check it isn't silently pulling the
> display far earlier than the word itself starts — this project has hit
> multi-second caption drift before from exactly that kind of indirection.
>
> **Don't guess at unclear audio.** If a word is genuinely ambiguous, caption
> it as `[UNINTELLIGIBLE]` or `???` rather than transcribing your best
> guess — a wrong guessed word is worse than an honest gap. If it's not a
> word at all (a laugh, a yell, a game-audio sting caught by the mic), don't
> caption it as if it were speech — either skip it or use `???`, don't
> invent text for a noise.

- **Font**: Bebas Neue, bold weight if a real bold static file is available;
  if only `BebasNeue-Regular.ttf` exists (it's the only weight Google Fonts
  ships), compensate with a heavier stroke rather than substituting a
  different family.
- **Style**: white fill, black stroke outline, plus a **solid black
  extrude/bevel** shadow — hard-edged, fully opaque, offset down-right, *not*
  a soft/blurred glow and *not* tinted blue. (An earlier version used a
  colored Gaussian-blur glow keyed to speaker — that's retired; there is no
  more speaker color-coding, see below.)
- **Layout**: up to 4 words on screen per card, split 2 words per line
  across at most 2 lines.
  - Top line's vertical **center** aligns with the center of the black
    divider bar between the facecam and gameplay halves of the 9:16 frame
    (measure this per composite — it moved slightly between layouts; it was
    ~y=652 on the reference layout, not a universal constant).
  - Bottom line sits below it with a gap equal to **20% of the top line's
    actual glyph height** — compute from the real text bounding box, not
    from a padded/bevel-inclusive canvas size (a canvas padded for the
    extrude effect will make the gap look much larger than 20% if you stack
    off its full height).
- **Animation**: pop-in (ease-out-back scale-up, ~0.14s), then a hard cut to
  the next card — no cross-fade between cards.
- **Card grouping**: from word-level timestamps, greedily group into cards of
  up to 4 words, breaking early on a >0.6s gap between words (natural
  pause). No speaker-based splitting — build cards from a single confirmed
  audio track's transcript (see "Audio track identification"; an earlier
  attempt to split cards across two tracks for red/green speaker coloring
  turned out to be built on two tracks that were actually the same program
  mix, not separate speakers).
- **Delivery as a soft overlay**: render captions as a transparent ProRes
  4444 overlay (Pillow → raw RGBA frames → `ffmpeg -c:v prores_ks -profile:v
  4444`) and composite with `ffmpeg overlay`, rather than burning text
  directly into the base encode. Keep the overlay `.mov` and the `cards.json`
  it was built from — that's what lets the style change later without
  re-cutting anything.
- **Karaoke-style active-word highlight**: the currently-spoken word is
  colored light green (`HIGHLIGHT_GREEN = (140,255,120)` in
  `render_captions.py`) while the rest of the card stays white — a standing
  feature on shorts going forward, not a one-off. `build_caption_cards.py`
  stores a `"words"` list per card (`{text, start, end, line}`, raw
  per-word timestamps, not lead-adjusted) alongside the existing `"lines"`
  strings; `render_captions.py` derives which word is active per frame with
  a small independent lead (`WORD_LEAD_S`) and **sticky** selection — once a
  word goes active it stays active until the next word's lead-adjusted
  start, so exactly one word is highlighted at every moment the card is on
  screen, never zero. Cards built before this feature (no `"words"` key)
  still render fine — `line_words()` falls back to splitting the old
  `"lines"` strings and simply shows no highlight.
- **Multi-speaker captions**: when a job has more than one speaker on the
  source audio, differentiate them — the on-screen caption always shows
  *whoever is currently talking* (not a fixed "main speaker"), and if a
  second person talks *over* them, a second, smaller (50% size) caption row
  appears beneath in yellow (`YELLOW = (255,214,0)` base, still with the
  same green active-word highlight) rather than mixing both voices into one
  line. Standing feature going forward whenever the source has multiple
  speakers, not a one-off.
  - Needs real diarization, not a guess — `scripts/transcribe_diarized.py`
    runs WhisperX transcription/alignment plus
    `whisperx.diarize.DiarizationPipeline` (model:
    `pyannote/speaker-diarization-community-1`) and tags each word with a
    `"speaker"` key. That model is **gated on Hugging Face** — needs an
    `HF_TOKEN` env var (a **Read**-scope token is enough) from an account
    that has accepted the model's terms at
    `https://hf.co/pyannote/speaker-diarization-community-1`. Ask the user
    for this token when a job needs diarization and none is cached; never
    write the token into a file — pass it as an env var on the command
    inline only.
  - `scripts/build_speaker_cards.py` turns diarized words into
    `{"primary": [cards...], "secondary": [cards...]}` (mapped through a
    short's segment list the same way `build_short_cards_from_segments.py`
    does). Algorithm: group each speaker's own words into per-speaker
    utterance cards independently (same grouping rule as single-speaker:
    break on >0.6s gap), merge all speakers' cards sorted by start time,
    then walk that merged list — a card that starts *after* the
    current primary card's end becomes the new primary card; a card that
    starts *before* the current primary card ends is a genuine
    simultaneous interjection and goes to the secondary list (split at the
    primary card's end boundary if the interjection runs longer, so the
    tail — now that the primary card is over — gets promoted to its own
    primary card instead of staying stuck in the secondary row).
  - `render_captions.py` accepts this dict shape directly (a plain list
    still works too, for single-speaker jobs) — `main()` tracks two
    independent card-index cursors and composites the secondary block
    stacked beneath wherever the primary block's bottom edge lands, both
    driven through the same `render_line_image`/karaoke-highlight machinery
    via a `style` dict (`PRIMARY_STYLE` vs `SECONDARY_STYLE`) so highlight
    logic, emoji handling, etc. aren't duplicated.
  - This only matters for jobs with genuinely distinct speakers on the
    chosen audio track — if the user picks a single full-mix track as
    "the" source and there's really only one person talking regularly (see
    "Audio track identification" — sparse/near-silent secondary tracks are
    a real possibility, confirm before assuming multi-speaker), diarization
    still runs but naturally produces one dominant speaker and an empty (or
    near-empty) secondary list, which is correct, not a bug.
  - **Diarization is very slow on this rig for a full-length VOD — budget
    hours, not minutes, and confirm the user actually wants to wait before
    committing to it on a long file.** Confirmed 2026-09-15 on a 4h51m
    recording: WhisperX ASR+alignment alone took ~3h19m, and diarization
    (pyannote, loaded *after* ASR finishes — same process, no incremental
    checkpoint in `transcribe_diarized.py`) was still running almost 2 hours
    later when the user killed it and asked for a normal single-speaker
    transcript instead. **Because there's no checkpoint between the ASR
    pass and the diarization pass, killing the job partway through loses
    the already-completed ASR work too** — the fallback isn't "resume from
    where it stopped," it's "start over with plain `transcribe.py`."
    **How to apply:** before kicking off `transcribe_diarized.py` on a VOD
    of stream length (multiple hours), tell the user roughly how long it's
    likely to take (ASR real-time-factor on this rig is roughly 0.7x the
    source duration, so a ~5h file is a ~3.5h ASR pass before diarization
    even starts) rather than just launching it silently in the background —
    multi-speaker captions are valuable but not worth hours of surprise
    wait time on a job that could've used plain `transcribe.py` (much
    faster, same ASR pass, no diarization stage) if the user would rather
    trade speaker-differentiated captions for turnaround time.

### Long-edit SRT captions

- **Build with `scripts/build_srt_multi_source.py`**, feeding it
  `timeline.source_range_report`'s `occurrences` list (matches the script's
  expected shape directly — no reformatting needed) plus the source's
  `words.json`. It word-maps through the actual cut, not the raw VOD
  timeline, and (as of 2026-09-16) forces a subtitle break at every clip
  boundary in addition to its gap/duration heuristics — **this fix matters**:
  when two unrelated clips are spliced back-to-back with zero gap (the
  normal case for a jump-cut edit), naive gap-only chunking merges their
  text into one nonsense caption (confirmed case: "Wow, this dump chest
  music is awesome. and I believe we are live." — two different moments,
  spliced). It also clamps word boundaries to the clip's actual frame range
  (≥50% of the word's duration must survive the cut) rather than requiring
  full containment, so a word that's mostly-but-not-entirely inside a clip
  still gets captioned instead of silently dropped at the cut point.
- **ASR reliably garbles sung, chanted, or exaggerated/performative speech**
  — WhisperX transcribes drunk karaoke, crowd chants, or bit-voices as
  confident-sounding nonsense rather than flagging low confidence (e.g.
  "muy bien, muy bien" transcribed as "Very good, very good!"; a triple
  "bah bah bah" transcribed as the single word "Baba."). This is not
  occasional — check the transcript against the actual audio for **any**
  segment the cut list or OBS markers describe as singing/karaoke/chanting/a
  bit, in every deliverable that includes it (a short AND the long edit both
  need the check independently if they overlap the same footage — fixing it
  in one does not fix the other). Same for a misheard proper noun/meme
  reference the user has already corrected once elsewhere in the same job
  (e.g. "Bride wife" → "Ride wife") — grep the full SRT for the wrong form,
  it's likely to recur anywhere that footage repeats (a cold-open teaser and
  its later chronological occurrence are two separate ASR passes over the
  same words and can be transcribed differently each time).
- Hand-correcting a caption line: match on the exact
  `HH:MM:SS,mmm --> HH:MM:SS,mmm\n<old text>` block (unique per cue) and
  replace in place — don't regenerate the whole file for a handful of fixes.

### Deliverable bundle: export + captions + metadata

When asked to "export," "prep for upload," or similar for a finished
`EDITS`-tier timeline, that means all of the following together, not just
the video file — do them in one pass rather than waiting to be asked for
each:

1. Render the timeline (`render.set_format_and_codec` mp4/H264,
   `render.set_settings` with `TargetDir`/`CustomName` pointed at the dated
   `EDITS` batch folder, `add_job` + `start`). **Always pass
   `ExportAudio: true` (and `ExportVideo: true`) explicitly in that
   `set_settings` call — don't rely on the default.** Confirmed
   2026-09-16: `timeline_frame.capture` (used constantly through a job for
   visual spot-checks) sets the *project's* shared render settings to
   `ExportVideo: True, ExportAudio: False` internally as an implementation
   detail of how it grabs a single frame — this persists at the project
   level, not scoped to that one capture, so a real render job queued any
   time after the last `timeline_frame.capture` call **silently comes out
   with zero audio streams** unless `ExportAudio` is explicitly set back to
   `true` first. This produced a fully "verified" (`duration_ratio: 1`,
   frame-exact) but completely silent 57-minute render — `render.verify_output`
   checks duration/frame-count, not stream presence, so it did not catch
   this. **After any render finishes, `ffprobe -show_streams` the output
   and confirm an `audio` stream is actually present** — that's the only
   reliable check here, since neither `get_job_status` nor `verify_output`
   inspects streams. `render.get_settings()` isn't available on this build
   to read the setting back before rendering, so the explicit `set_settings`
   call before every real render job is the only safeguard.

   Verify completion with `render.verify_output`, not just
   `get_job_status` — a `CompletionPercentage` read shortly after `start`
   can show single digits with an `EstimatedTimeRemainingInMs` in the tens
   of minutes; don't treat a file that already exists on disk mid-render as
   finished (see Non-negotiable 4a — the same "looks done but isn't" trap
   applies to Resolve's own render, not just ffmpeg).
2. Build the `.srt` per "Long-edit SRT captions" above, including the
   ASR-garble spot-check, saved alongside the video in the same dated
   `EDITS` folder.
3. Write the `*_metadata.txt` deliverable (TITLE/DESCRIPTION/TAGS, and a
   CHAPTERS block with `record_frame/fps` timestamps for every structural
   beat if the cut list has named scenes) in the same folder, matching the
   existing file's format exactly — see an existing `*_metadata.txt` in a
   prior batch folder for the template rather than inventing a new shape.
   Apply the episode-numbering offset (see
   [[project-valheim-episode-numbering]]-style memory for this series) to
   the TITLE if one is in effect for the job.

### Profanity → caption emoji substitution

On-screen caption text (regardless of whether the word is also censored in
audio — see Censoring below) replaces these words with emoji:

| Word | Caption replacement |
|---|---|
| ass | 🍎 or 🐴 |
| fuck | 🤭🤭🤭 |
| shit | 💩 |
| faggot | ⚠️⚠️⚠️ |

This is a caption-text rule only. Whether the *audio* underneath also gets
cut depends on the Censoring rules below — "ass" and "shit" keep their audio,
only the on-screen word is swapped.

## Censoring

Three tiers, applied to both the full-VOD cleanup and the highlight edit:

1. **Cut the whole scene** (not just the word): racial slurs, homophobic
   slurs (e.g. "faggot"), and racially-charged conversation topics generally
   — even if the framing is self-aware or joking. This is a scene-level cut
   via the frame-range excision method (never muting — see Resolve
   limitations above).
2. **Excise just the word**: "fuck" and its variants. Cut the exact
   word-length frame range out of the timeline.
3. **Leave alone**: "shit", "ass", and other general profanity. Don't touch
   the audio or cut anything — only the caption substitution above applies
   to these in shorts/captioned deliverables.

For anything not covered by tiers 1-2 that still reads as a swear word,
**flag the timestamp for the user's manual review** rather than acting on
it — report a list, don't guess at scope creep beyond what's specified here.

## User preferences (full detail, across every job on this pipeline)

Everything below is a standing preference confirmed by the user, either
directly stated or confirmed by their reaction to a specific deliverable.
Sections already covered in full detail above (audio-track confirmation,
file destinations/naming, caption styling, censoring tiers) aren't repeated
here — this section covers everything else.

### Execution style

- **Work through the whole brief without stopping to check in.** Once the
  scope is set (length, tone, censoring rules), don't pause for
  confirmation on individual cuts, marker placement, or shot selection —
  report status/progress as things complete, not as permission requests.
  The explicit exceptions: audio-track identification (always confirm
  first, see "Audio track identification"), and anything that would
  overwrite or discard existing work non-recoverably.
- When background renders are running, **give brief status pings as jobs
  complete** rather than going silent until everything is done — one short
  sentence per completion is enough ("short2 is done, only short3 and the
  full remux left"), not a running commentary on every ffmpeg progress line.
- If the user corrects something mid-flight (wrong speaker, wrong track,
  wrong folder), **stop the specific thing that's wrong immediately** —
  including killing in-flight background jobs that depend on the bad
  assumption — rather than letting them finish and fixing it after. Confirm
  what was stopped and why in one line, then wait for direction rather than
  guessing at the fix, *unless* the fix is unambiguous (e.g. the user
  already told you which track to use going forward).
- **Treat a stated ceiling as a ceiling.** "30-40 minutes," "at longest 40
  min," "4-5 shorts," "4 words max on screen" — all of these are upper
  bounds. Land inside the window with the strongest material rather than
  padding to the top of it. This was directly confirmed on the first job:
  asked for "at longest 40 min," delivered ~20.5 min, and the shorter length
  was explicitly praised, not flagged as under-delivering.
- **Prioritize humor over "importance."** When selecting what makes the
  highlight edit or a short, the funniest moments win over narratively
  significant ones (boss fights, milestones) unless the user says otherwise.
  Funny and significant aren't mutually exclusive — a boss fight that's also
  funny is a natural pick — but significance alone isn't enough to include
  something unfunny.
- **When a batch of shorts has misses, don't defend them.** If the user says
  a clip "wasn't any good," drop it without arguing for it and go find
  fresh material — they're evaluating comedic/entertainment quality, which
  is inherently a judgment call that's theirs to make, not something to
  relitigate.

### Structure & hook convention

- **Cold-open / preview-clip-at-front convention**: on the full highlight
  edit, duplicate a short, high-energy/funny moment from later in the
  edit and place it again at the very front, before the "real" start — a
  YouTube-style cold open to hook viewers before the normal chronological
  content begins. This was explicitly re-confirmed on a later job ("keep
  the [preview clip] at the front like you did") — once established for a
  given channel/style, keep doing it on subsequent edits without being
  asked again.
- **Real spoken introduction, spliced in after the cold open**: the user is
  starting to record an actual intro ("hey guys, welcome back...") at some
  point in the raw footage — distinct from the cold-open trick above, which
  reuses a funny moment. When present, structure is [cold-open funny clip]
  → [real intro] → [main chronological content]. Identifying "which stretch
  is the intro" is a judgment call (it won't always be at the literal start
  of the recording — see camera-setup note below) — flag what was found for
  a quick sanity check the first time this comes up on a given job, same as
  any other new structural choice.
- **Trim camera-setup footage from the very start of the raw recording, not
  just off-topic *talk*.** A recording can start with several minutes of
  dead visual time before the streamer settles at their desk — camera
  pointed at the ceiling/wall, close-up fumbling while adjusting the webcam
  physically — while the *audio* is already live and people are already
  talking normally throughout it. This defeats a transcript-only scan for
  "behind the scenes" content (see the non-negotiable "video editing"
  section above) since there's no silence and no logistics/technical talk
  to key off — it's a purely visual problem. Confirmed on one job: the
  webcam feed was solid black for the first ~60s, then pointed at a
  ceiling/wall for another ~70s, then handheld/close-up for ~30s while
  being repositioned, before settling into the normal framing around 199s
  in — all while dialogue played normally the whole time (including the
  start of a joke that was already mid-flow before the camera settled).
  **Check the very start of every new raw recording visually** (extract a
  handful of frames across the first 2-4 minutes, not just t=0) before
  trusting that "the recording starts" means "the footage is usable from
  frame zero" — cut forward to wherever the framing actually settles, even
  if it clips a few seconds off the front of whatever's being said at that
  moment. This applies to the main cut *and* to any short that happens to
  start inside that same window — check both, a short built from an early
  timestamp can inherit the exact same problem independently.
- **Timeline markers while cutting**: yellow = funny moment, cyan =
  boss-fight / major set-piece. Drop these as you go through the transcript
  and build the cut, not as an afterthought — they help the user scrub the
  timeline later and orient themselves in the edit.
- **Cut "behind-the-curtain" / off-content talk** from the highlight edit
  unless it's independently funny — logistics chat, stream housekeeping,
  meta talk about the recording/setup itself, sponsor or technical asides.
  This is distinct from the content-moderation Censoring tiers above; it's
  a pacing/quality judgment, not a safety one.

### Deliverables beyond the video file itself

- **Write a YouTube description** for the highlight edit — this is a standing
  deliverable alongside the edit, not a one-off ask. **Format, confirmed
  2026-09-16: exactly two sentences, not a list of bits.** First, one single
  funny line in the user's own voice (dry, blunt, casual — not a strung-
  together recap of multiple jokes/moments; picking one and landing it beats
  cramming several in). Second, one plain, logical/serious sentence
  describing what actually happens in the episode (the real content beats,
  not jokes). Do not go back to the earlier style of chaining 3-4 bit
  references into one descriptive paragraph — that was explicitly corrected.
- **Every mid-length edit (the `EDITS` deliverable) always gets an
  accompanying `.srt`** — not just when captions are separately requested.
  Generate it automatically as part of finishing that edit, extrapolated
  from the same word-level WhisperX transcript used for cutting, with
  timestamps reflecting the *final cut's* timeline (not the raw VOD's
  original timestamps — cuts shift everything downstream). **Save the
  `.srt` in the same dated folder as the main cut video itself**
  (`E:\Streaming\Videos\EDITS\MM-DD-YYYY_GAME\`), named to match the video
  file so the pairing is obvious.
- **Every mid-length edit also gets a YouTube tag cloud** — a standing
  deliverable alongside the description and `.srt`, not a one-off ask.
  - Comma-separated tags, optimized for engagement and surfacing to new
    viewers (mix of broad/high-traffic terms — game name, genre, "funny
    moments," "highlights" — and specific terms pulled from the actual
    content — named bits, running jokes, people/games referenced — rather
    than only generic tags).
  - **Hard cap: 450 characters total** for the whole comma-separated string
    (YouTube's own tag field limit is 500; stop meaningfully short of it).
  - Save as a `.txt` file (comma-separated, one line) in the same dated
    folder as the main cut video, named to match it — alongside the `.srt`
    and description.
- When the user asks to **sanity-check audio remotely** ("drop one of the
  shorts in this chat," "send a different clip of my voice"), the fastest
  useful response is a short (~10s) audio-only sample cut directly from the
  candidate source, sent immediately — not a full re-render. Use
  `SendUserFile` for these; don't make the user wait for a full composite
  just to confirm a track choice.
- If the user names actual people in the recording (e.g. "there should be 3
  speakers, Ben, Jared, and Brian"), and the pipeline is doing any kind of
  speaker identification, **cross-check the claimed identity against
  something verifiable** where possible — e.g. does the audio track that's
  supposed to be the on-camera streamer's voice actually line up with the
  facecam's mouth movement at a sampled timestamp. Don't rely solely on an
  algorithmic guess (track index, loudest channel, first-detected speaker)
  when a physical cross-check like lip-sync is available and the stakes of
  getting it wrong are high (as they were here).

### Resource/environment preferences

- **Never let `C:` (the SSD) fill up with permanent large files** — it's
  fine as scratch space mid-job (it's faster than the `E:` HDD for active
  transcoding/processing), but every finished deliverable and any
  multi-gigabyte intermediate that outlives the job belongs on `E:`. This
  project has actually run `C:` out of space once already from accumulated
  video intermediates — check free space before starting a large render
  batch, and prefer working directly on `E:` for anything already
  multi-gigabyte rather than round-tripping through `C:` first.
- Running several large ffmpeg jobs fully in parallel against the same
  physical disk can starve *other* things of I/O/CPU on this machine badly
  enough to make the Resolve bridge stop responding — if Resolve
  connectivity gets flaky while a batch of renders is running, that's a
  plausible cause worth checking before assuming the bridge itself is
  broken (see the Resolve connection section above for the actual
  diagnostic steps).
- **Watch for the destination folder moving out from under a job in
  progress.** The user's own `E:\Streaming\...` structure has been
  reorganized manually mid-session before (a folder moved to a new parent
  while renders targeting the old path were in flight). If a write fails
  with "no such file or directory" partway through a batch, check whether
  the destination folder itself has moved before assuming anything else is
  wrong, then just re-target the new path — don't recreate the old
  structure.
