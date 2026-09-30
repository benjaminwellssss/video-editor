"""Turn a caption's editor note (plain English, written in the caption
editor as *note*) into animation parameters for render_captions.py.

The note stays the source of truth in captions.json ("note": "gentle grow and
vibrate of the text"); this reads it at render time, so re-editing the note
in the editor and re-rendering is all it takes. A card may instead carry an
explicit "fx" dict, which wins over the note.

Per-card effects (they apply to that card's caption only, never the video):
  grow / bigger / swell  - scale up slowly across the card's whole time on screen
  zoom / punch           - scale up fast (punches to size in the first third)
  impact                 - alone: a fast punch-in; with other words: makes them 1.3x stronger
  shake / rumble         - jitter position at ~24 Hz (big amplitudes also rock/rotate)
  vibrate / jitter       - small fast jitter at ~34 Hz (8 px at 1x)
  dance / bounce / groove/wiggle - a smooth vertical bob (not jittery like shake)
  glow / shine / holy / neon / radiant / halo - a brief radiant flash behind the text
  a color word (red/green/blue/yellow/orange/purple/pink/white/black/cyan)
    - overrides that card's text color, on top of any of the above
  a bare http(s) URL     - overlay that image/gif near the caption; "until
    the end (of the video)" makes it persist to the end, otherwise it shows
    for a few seconds. Where it starts (its resting position - there's no
    slide-in animation for a note-driven overlay, just where it appears):
    a grid phrase like "top left", "middle right", "bottom center",
    "dead center", or a single "top"/"bottom"/"left"/"right"/"center"
    anchors it to that spot on the full frame; "above"/"below" (or
    under/over/beneath), with no grid phrase present, instead anchors it
    relative to the caption itself (default: below). Grid phrases win if
    both appear.

Intensity words multiply the effect: gentle/slight/subtle/soft/little 0.5x,
"very" 1.3x, "extremely"/huge/massive 1.5x, violent/hard/intense/heavy 2x,
maximum/max 3x (the cap). No intensity word = 1x.

Three cross-card mechanisms, applied by render_captions.py using the helpers
below (not by fx_from_note itself, since they need to see the whole card
list for a lane):
  - a note containing progressively/gradually/increasingly marks the start
    of a RAMP: the triggering effect ramps up linearly across it and every
    contiguous following card that shares the same effect, ending at
    whatever's the strongest intensity word found anywhere in that run.
  - "make all instances of "X, Y" do a <effect>" (or "every/whenever/any
    time it says") applies <effect> to every card in the lane whose text
    is one of the quoted words, wherever it appears in the timeline.
  - a note naming a screen position for the CAPTION TEXT itself - "near the
    bottom", "under my face", "under my chin" (bottom anchor, for a
    full-facecam segment where the normal seam position would sit over the
    subject's face) or "centered again"/"back to normal"/bare "centered"
    (back to the normal seam anchor) - PERSISTS from that card onward until
    the next such note, the same way a hand-editor would expect "make
    everything from here down sit lower" to work. This is distinct from a
    note's image-overlay position (parse_image_position above), which only
    ever places that one note's image and never moves the caption text.

A note with no recognised effect word, color, or URL returns no fx and is
reported by describe(), so an instruction the renderer can't do is never
silently dropped - it comes back to a human (or Claude) to handle by hand.
"""
import re

SCALE_SLOW = {"grow", "growing", "grows", "bigger", "swell", "enlarge", "expand"}
SCALE_FAST = {"zoom", "zooming", "punch", "push", "pop", "slam"}
SHAKE = {"shake", "shaking", "rumble", "quake", "camera-shake"}
VIBRATE = {"vibrate", "vibrating", "vibration", "jitter", "tremble", "buzz"}
DANCE = {"dance", "dancing", "bop", "bopping", "bounce", "bouncing", "groove", "grooving", "wiggle", "wiggling"}
GLOW = {"glow", "glowing", "holy", "shine", "shining", "radiant", "neon", "halo"}

COLOR_WORDS = {
    "red": (230, 40, 40, 255),
    "green": (80, 230, 90, 255),
    "blue": (70, 140, 255, 255),
    "yellow": (255, 210, 0, 255),
    "orange": (255, 140, 40, 255),
    "purple": (170, 90, 255, 255),
    "pink": (255, 110, 190, 255),
    "white": (255, 255, 255, 255),
    "black": (25, 25, 25, 255),
    "cyan": (70, 220, 220, 255),
}

INTENSITY = {
    "gentle": 0.5, "gently": 0.5, "slight": 0.5, "slightly": 0.5, "subtle": 0.5, "soft": 0.5, "light": 0.5, "little": 0.5,
    "very": 1.3, "impact": 1.3, "extremely": 1.5, "extreme": 1.5, "insane": 1.5, "insanely": 1.5, "massive": 1.5, "huge": 1.5,
    "violent": 2.0, "violently": 2.0, "hard": 2.0, "intense": 2.0, "intensely": 2.0, "aggressive": 2.0, "heavy": 2.0,
    "maximum": 3.0, "max": 3.0,
}
MAX_FACTOR = 3.0
MAX_SCALE = 1.9

RAMP_WORDS = {"progressively", "progressive", "gradually", "gradual", "increasingly", "increasing"}

URL_RE = re.compile(r"https?://\S+")

# Absolute on-screen anchor for a note-driven image overlay - checked longest
# (most specific) phrase first so "top left" doesn't get shadowed by a bare
# "top" match. Values are (vertical, horizontal) grid positions.
POSITION_PHRASES = [
    ("top left", ("top", "left")), ("top-left", ("top", "left")),
    ("top right", ("top", "right")), ("top-right", ("top", "right")),
    ("top center", ("top", "center")), ("top middle", ("top", "center")), ("top-center", ("top", "center")),
    ("bottom left", ("bottom", "left")), ("bottom-left", ("bottom", "left")),
    ("bottom right", ("bottom", "right")), ("bottom-right", ("bottom", "right")),
    ("bottom center", ("bottom", "center")), ("bottom middle", ("bottom", "center")), ("bottom-center", ("bottom", "center")),
    ("middle left", ("middle", "left")), ("center left", ("middle", "left")), ("middle-left", ("middle", "left")),
    ("middle right", ("middle", "right")), ("center right", ("middle", "right")), ("middle-right", ("middle", "right")),
    ("dead center", ("middle", "center")), ("dead centre", ("middle", "center")),
    ("centered", ("middle", "center")), ("centred", ("middle", "center")),
    ("middle center", ("middle", "center")),
]
POSITION_SINGLE = {
    "top": ("top", "center"), "bottom": ("bottom", "center"),
    "left": ("middle", "left"), "right": ("middle", "right"),
    "center": ("middle", "center"), "centre": ("middle", "center"), "middle": ("middle", "center"),
}


# Persisting anchor for the CAPTION TEXT itself - checked as phrases first
# (most specific) then bare single words, same pattern as the image-position
# parser above but a completely separate concern (moves the caption block,
# not a note's image overlay).
TEXT_POSITION_PHRASES = [
    ("near the bottom", "bottom"), ("under my face", "bottom"), ("under the face", "bottom"),
    ("under my chin", "bottom"), ("under the chin", "bottom"), ("lower third", "bottom"),
    ("bottom of the screen", "bottom"), ("bottom of screen", "bottom"),
    ("centered again", "default"), ("center again", "default"), ("centred again", "default"),
    ("back to normal", "default"), ("back to center", "default"), ("back to centered", "default"),
    ("back to centre", "default"), ("back to the seam", "default"), ("back to the middle", "default"),
    ("normal position", "default"), ("default position", "default"), ("normal again", "default"),
]
TEXT_POSITION_SINGLE = {"bottom": "bottom", "centered": "default", "centred": "default", "center": "default"}


def parse_text_position(note):
    """A persisting on-screen anchor for the caption TEXT itself ('bottom' or
    'default'), or None if the note doesn't mention one. See the module
    docstring's cross-card mechanisms section - the caller (render_captions.py)
    carries the last-seen value forward across cards, this function only
    reads one note."""
    if not note:
        return None
    low = note.lower()
    for phrase, val in TEXT_POSITION_PHRASES:
        if phrase in low:
            return val
    for w in _words(note):
        if w in TEXT_POSITION_SINGLE:
            return TEXT_POSITION_SINGLE[w]
    return None


def parse_image_position(note):
    """An absolute (vertical, horizontal) grid anchor named in the note -
    "top left", "middle right", "bottom center", "dead center", or a bare
    "top"/"bottom"/"left"/"right"/"center" - or None if it doesn't name one."""
    low = note.lower()
    for phrase, pos in POSITION_PHRASES:
        if phrase in low:
            return pos
    for w in _words(note):
        if w in POSITION_SINGLE:
            return POSITION_SINGLE[w]
    return None
GLOBAL_RE = re.compile(
    r'(?:make\s+all\s+instances\s+of|every\s+instance\s+of|every\s+time\s+it\s+says|'
    r'whenever\s+it\s+says|any\s+time\s+it\s+says)'
    r'\s+(.+?)\s+'
    r'(?:do\s+(?:a\s+|an\s+)?|should\s+(?:be\s+)?)(.+)',
    re.I,
)
QUOTED_RE = re.compile(r'[\'"‘“]([^\'"’”]+)[\'"’”]')
END_OF_VIDEO_RE = re.compile(r"(?:until|till|til|to)\s+(?:the\s+)?end\b|rest\s+of\s+the\s+video", re.I)


def _words(note):
    return set(re.findall(r"[a-z]+(?:-[a-z]+)?", note.lower()))


def note_factor(note):
    """The plain intensity multiplier a note carries (product of all
    intensity words found, capped at MAX_FACTOR), independent of which
    effect(s) it goes with. Used to compute ramps across several cards."""
    if not note:
        return 1.0
    factor = 1.0
    for w in _words(note) & INTENSITY.keys():
        factor *= INTENSITY[w]
    return min(factor, MAX_FACTOR)


def is_ramp_trigger(note):
    if not note:
        return False
    return bool(_words(note) & RAMP_WORDS)


def parse_global_instruction(note):
    """Return (target_words, effect_note) for a note naming which words to
    apply an effect to everywhere they appear - "make all instances of "X,
    Y" do a <effect>", "every instance of 'X' or 'Y' should <effect>", etc.
    - or None if the note isn't one of these. The target span may hold one
    quoted phrase ("X, and Y") or several separately-quoted words ('X' or
    'Y'); either way every word in it (minus and/or) becomes a target."""
    if not note:
        return None
    m = GLOBAL_RE.search(note)
    if not m:
        return None
    targets_raw, effect_note = m.groups()
    quoted = QUOTED_RE.findall(targets_raw)
    word_source = " ".join(quoted) if quoted else targets_raw
    targets = [w for w in re.findall(r"[a-z']+", word_source.lower()) if w not in ("and", "or")]
    if not targets:
        return None
    return targets, effect_note.strip()


def fx_from_note(note):
    """Return an fx dict for the note, or {} if nothing in it is recognised."""
    if not note:
        return {}
    words = _words(note)
    factor = note_factor(note)

    fx = {}
    if words & SCALE_SLOW:
        fx["scale_to"] = min(1.0 + 0.30 * factor, MAX_SCALE)
    if words & SCALE_FAST:
        fx["scale_to"] = min(1.0 + 0.35 * factor, MAX_SCALE)
        fx["scale_fast"] = True
    if words & SHAKE:
        fx["shake_px"] = 10.0 * factor
        fx["shake_hz"] = 24.0
    if words & VIBRATE and not (words & SHAKE):
        fx["shake_px"] = 8.0 * factor
        fx["shake_hz"] = 34.0
    elif words & VIBRATE:
        fx["shake_px"] = max(fx["shake_px"], 8.0 * factor)
    if words & DANCE:
        fx["dance_px"] = 14.0 * factor
        fx["dance_hz"] = 2.2
    if words & GLOW:
        fx["glow"] = True
    if not fx and "impact" in words:  # "impact" on its own = a fast punch-in
        fx["scale_to"] = min(1.0 + 0.35 * factor, MAX_SCALE)
        fx["scale_fast"] = True

    color_hit = words & COLOR_WORDS.keys()
    if color_hit:
        fx["color"] = COLOR_WORDS[sorted(color_hit)[0]]

    m = URL_RE.search(note)
    if m:
        fx["image_url"] = m.group(0).rstrip(").,”’")
        low = note.lower()
        # default: the image stays on screen for exactly as long as the caption
        # card it's attached to (not a fixed guess) - images lingering well past
        # their card was a recurring problem. "until end"/"rest of the video"
        # still overrides to the end of the clip.
        fx["image_duration"] = "end" if END_OF_VIDEO_RE.search(low) else "card"
        grid = parse_image_position(note)
        if grid:
            fx["image_position"] = grid  # absolute (vertical, horizontal) anchor on the full frame
        elif any(w in low for w in ("above", "over")):
            fx["image_position"] = "above"  # relative to the caption, legacy default
        else:
            fx["image_position"] = "below"  # default, also covers under/below/beneath

    return fx


def describe(note, fx):
    if not fx:
        return f'NOT UNDERSTOOD (no effect word found), rendered plain: "{note}"'
    parts = []
    if "scale_to" in fx:
        parts.append(f'{"fast zoom" if fx.get("scale_fast") else "slow grow"} to {fx["scale_to"]:.2f}x')
    if "shake_px" in fx:
        parts.append(f'shake {fx["shake_px"]:.0f}px @ {fx["shake_hz"]:.0f}Hz')
    if "dance_px" in fx:
        parts.append(f'dance {fx["dance_px"]:.0f}px @ {fx["dance_hz"]:.1f}Hz')
    if fx.get("glow"):
        parts.append("glow flash")
    if "color" in fx:
        parts.append(f'color -> rgba{tuple(fx["color"])}')
    if "image_url" in fx:
        if fx["image_duration"] == "end":
            dur = "until end of video"
        elif fx["image_duration"] == "card":
            dur = "card duration"
        else:
            dur = f'{fx["image_duration"]:.0f}s'
        pos = fx["image_position"]
        pos_str = " ".join(pos) if isinstance(pos, tuple) else pos
        parts.append(f'image overlay ({pos_str}, {dur}): {fx["image_url"]}')
    return ", ".join(parts) + f' <- "{note}"'
