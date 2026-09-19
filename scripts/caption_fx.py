"""Turn a caption's editor note (plain English, written in the caption
editor as *note*) into animation parameters for render_captions.py.

The note stays the source of truth in captions.json ("note": "gentle grow and
vibrate of the text"); this reads it at render time, so re-editing the note
in the editor and re-rendering is all it takes. A card may instead carry an
explicit "fx" dict, which wins over the note.

Effects (they apply to that card's caption only, never the video):
  grow / bigger / swell  - scale up slowly across the card's whole time on screen
  zoom / punch           - scale up fast (punches to size in the first third)
  impact                 - alone: a fast punch-in; with other words: makes them 1.3x stronger
  shake / rumble         - jitter position at ~24 Hz (big amplitudes also rock/rotate)
  vibrate / jitter       - small fast jitter at ~34 Hz (8 px at 1x)

Intensity words multiply the effect: gentle/slight/subtle/soft 0.5x,
"very" 1.3x, "extremely"/huge/massive 1.5x, violent/hard/intense/heavy 2x
(so "extremely violent" is 3x, the cap). No intensity word = 1x.

A note with no recognised effect word returns no fx and is reported by
describe(), so an instruction the renderer can't do is never silently
dropped — it comes back to a human (or Claude) to handle by hand.
"""
import re

SCALE_SLOW = {"grow", "growing", "grows", "bigger", "swell", "enlarge", "expand"}
SCALE_FAST = {"zoom", "zooming", "punch", "push", "pop", "slam"}
SHAKE = {"shake", "shaking", "rumble", "quake", "camera-shake"}
VIBRATE = {"vibrate", "vibrating", "vibration", "jitter", "tremble", "buzz"}

INTENSITY = {
    "gentle": 0.5, "gently": 0.5, "slight": 0.5, "slightly": 0.5, "subtle": 0.5, "soft": 0.5, "light": 0.5,
    "very": 1.3, "impact": 1.3, "extremely": 1.5, "extreme": 1.5, "insane": 1.5, "insanely": 1.5, "massive": 1.5, "huge": 1.5,
    "violent": 2.0, "violently": 2.0, "hard": 2.0, "intense": 2.0, "intensely": 2.0, "aggressive": 2.0, "heavy": 2.0,
}
MAX_FACTOR = 3.0
MAX_SCALE = 1.9


def fx_from_note(note):
    """Return an fx dict for the note, or {} if nothing in it is recognised."""
    if not note:
        return {}
    words = set(re.findall(r"[a-z]+(?:-[a-z]+)?", note.lower()))
    factor = 1.0
    for w in words & INTENSITY.keys():
        factor *= INTENSITY[w]
    factor = min(factor, MAX_FACTOR)

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
    if not fx and "impact" in words:  # "impact" on its own = a fast punch-in
        fx["scale_to"] = min(1.0 + 0.35 * factor, MAX_SCALE)
        fx["scale_fast"] = True
    return fx


def describe(note, fx):
    if not fx:
        return f'NOT UNDERSTOOD (no effect word found), rendered plain: "{note}"'
    parts = []
    if "scale_to" in fx:
        parts.append(f'{"fast zoom" if fx.get("scale_fast") else "slow grow"} to {fx["scale_to"]:.2f}x')
    if "shake_px" in fx:
        parts.append(f'shake {fx["shake_px"]:.0f}px @ {fx["shake_hz"]:.0f}Hz')
    return ", ".join(parts) + f' <- "{note}"'
