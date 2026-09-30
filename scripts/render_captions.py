"""Render animated pop-in captions (up to 2 lines x 2 words) as a transparent overlay video.

Usage: <venv-python> render_captions.py <cards.json> <duration_s> <out.mov>

cards.json is either:
  - a flat list of {"start", "end", "lines", "words"?, "fill"?, "lane"?, "note"?}. "lane"
    (default 0) is a simultaneous-caption timeline from the caption editor:
    lane 0 is the big main caption on the seam, each further lane is drawn
    smaller and stacks beneath it, so several speakers can be on screen at
    once. Within a lane the newest card wins if timings overlap. "note" is an
    editor note that drives effects (see caption_fx.py), never drawn; or
  - {"primary": [...same card shape...], "secondary": [...same card shape...]}
    for multi-speaker jobs — "secondary" cards render as a smaller (50%),
    yellow-base second caption row beneath whichever primary card is showing,
    for moments where a second speaker talks over the first. Both lists use
    word-level "speaker"-turn card breaks (see build_speaker_cards.py) so at
    most one speaker's text is ever in a given card.

  Optional per-card "fill": [r, g, b, a] overrides the base word color for
  that card, ignoring the style's normal white/yellow default — used to
  color-code single-word caption cards by diarized speaker (see
  build_speaker_colors.py). Stroke/extrude shadow stay black regardless.
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from caption_fx import MAX_FACTOR, describe, fx_from_note, is_ramp_trigger, note_factor, parse_global_instruction, parse_text_position

W, H = 1080, 1920
FPS = 30
FONTS_DIR = r"C:\Users\Bem\Desktop\video-editor\assets\fonts"
# Caption font options - picked in the caption editor (saved to the job's
# "*_speakers.json" sidecar as {"font": "<name>"}), auto-discovered here by
# find_font_path(). "Bebas Neue" is the default when no sidecar/font is set.
# Bebas Neue is the condensed house style; the others are wide/heavy faces
# chosen for raw legibility at small mobile caption sizes.
FONTS = {
    "Bebas Neue": "BebasNeue-Regular.ttf",
    "Montserrat Black": "Montserrat-Black.ttf",
    "Anton": "Anton-Regular.ttf",
    "Archivo Black": "ArchivoBlack-Regular.ttf",
    "Poppins ExtraBold": "Poppins-ExtraBold.ttf",
}
DEFAULT_FONT = "Bebas Neue"
EMOJI_FONT_PATH = r"C:\Windows\Fonts\seguiemj.ttf"
FONT_SIZE = 150
FONT_SIZE_SECONDARY = 75  # 50% size, matching render_handle.py's established scale-down
BAR_CENTER_Y = 670  # 2026-09-30: raised for the new Resolve-build + ffmpeg-center-crop short
# layout's large full-width facecam.exe window (bottom edge ~y=575, vs the old small PiP box
# this constant was originally tuned for) - verified empirically by rendering a single-word
# test card, measuring its rendered bbox, and compositing it onto an actual frame before
# committing (user-approved via screenshot).
TEXT_ANCHOR_BOTTOM = 1550  # "near the bottom" / "under my face" text position - low enough to clear a full-facecam subject's face, high enough to leave room for a 2-line block + platform UI safe zone above H=1920


def find_font_choice(cards_path):
    """The font name saved in this job's "*_speakers.json" sidecar (the
    caption editor writes {"font": "<name>", "speakers": [...]} there once a
    font is picked - see caption-editor's Font dropdown). Falls back to
    DEFAULT_FONT if there's no sidecar, it's the old plain-array speakers
    format, or it doesn't name a font. cards_path is exactly sys.argv[1]."""
    base = os.path.basename(cards_path)
    for suffix in ("_cards.json",):
        if base.endswith(suffix):
            sidecar = os.path.join(os.path.dirname(cards_path), base[: -len(suffix)] + "_speakers.json")
            break
    else:
        return DEFAULT_FONT
    if not os.path.exists(sidecar):
        return DEFAULT_FONT
    try:
        data = json.load(open(sidecar, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DEFAULT_FONT
    if isinstance(data, dict) and data.get("font") in FONTS:
        return data["font"]
    return DEFAULT_FONT
LINE_SPACING_FRAC = 0.20  # gap between top and bottom line = 20% of top line's text height
SECONDARY_GAP_FRAC = 0.35  # gap between primary block's bottom and secondary block's top
POP_DURATION = 0.14  # seconds

STROKE_WIDTH = 7
STROKE_WIDTH_SECONDARY = 4  # matches render_handle.py's 7px->4px scale-down
EXTRUDE_DEPTH = 10  # px of solid black extrude/bevel behind the text, down-right
EXTRUDE_DEPTH_SECONDARY = 5
WHITE = (255, 255, 255, 255)
YELLOW = (255, 214, 0, 255)  # secondary caption row's base color (instead of white)
HIGHLIGHT_GREEN = (140, 255, 120, 255)  # currently-spoken word, both rows
WORD_GAP = 24  # px between words within a line (wider than RUN_GAP's within-word stitching)
WORD_GAP_SECONDARY = 12

# Bebas Neue has no emoji glyphs (renders as a tofu box) — profanity
# substitutions (see build_caption_cards.py EMOJI_SUBS) need the system color
# emoji font instead, rendered as a separate run and stitched in.
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")

font = ImageFont.truetype(os.path.join(FONTS_DIR, FONTS[DEFAULT_FONT]), FONT_SIZE)
emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, FONT_SIZE)
font_secondary = ImageFont.truetype(os.path.join(FONTS_DIR, FONTS[DEFAULT_FONT]), FONT_SIZE_SECONDARY)
emoji_font_secondary = ImageFont.truetype(EMOJI_FONT_PATH, FONT_SIZE_SECONDARY)

# A "style" bundles everything that scales together between the primary and
# secondary caption rows, so the render_* functions don't need two copies.
# main() may swap "font" in place once it knows which font this job picked
# (see apply_font_choice) - every function below takes `style` as a dict and
# reads style["font"] at call time, so mutating these two dicts in place,
# rather than rebinding them, is what makes that swap actually take effect
# everywhere (including in default-parameter bindings captured at import).
PRIMARY_STYLE = {
    "font": font, "emoji_font": emoji_font,
    "stroke_width": STROKE_WIDTH, "extrude_depth": EXTRUDE_DEPTH,
    "word_gap": WORD_GAP, "base_fill": WHITE,
}
SECONDARY_STYLE = {
    "font": font_secondary, "emoji_font": emoji_font_secondary,
    "stroke_width": STROKE_WIDTH_SECONDARY, "extrude_depth": EXTRUDE_DEPTH_SECONDARY,
    "word_gap": WORD_GAP_SECONDARY, "base_fill": YELLOW,
}


def apply_font_choice(font_name):
    """Reload PRIMARY_STYLE/SECONDARY_STYLE's fonts in place for font_name (a
    key in FONTS). Called once from main() with find_font_choice()'s result;
    a no-op if font_name is already DEFAULT_FONT since the module-level
    globals above already loaded it."""
    if font_name not in FONTS or font_name == DEFAULT_FONT:
        return
    path = os.path.join(FONTS_DIR, FONTS[font_name])
    PRIMARY_STYLE["font"] = ImageFont.truetype(path, FONT_SIZE)
    SECONDARY_STYLE["font"] = ImageFont.truetype(path, FONT_SIZE_SECONDARY)


def split_runs(text):
    """Split into (is_emoji, substring) runs, preserving order."""
    runs = []
    for ch in text:
        is_e = bool(EMOJI_RE.match(ch))
        if runs and runs[-1][0] == is_e:
            runs[-1] = (is_e, runs[-1][1] + ch)
        else:
            runs.append((is_e, ch))
    return runs


def render_text_run(text, style, fill):
    """Bebas Neue run: solid fill (base color, or highlight green for the
    active word), black stroke, solid black extrude/bevel shadow."""
    f, stroke_width, extrude_depth = style["font"], style["stroke_width"], style["extrude_depth"]
    probe = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    pd = ImageDraw.Draw(probe)
    bbox = pd.textbbox((0, 0), text, font=f, stroke_width=stroke_width)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = extrude_depth + stroke_width + 10
    canvas = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    ox, oy = pad - bbox[0], pad - bbox[1]

    extrude = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ed = ImageDraw.Draw(extrude)
    for depth in range(extrude_depth, 0, -1):
        ed.text((ox + depth, oy + depth), text, font=f,
                 fill=(0, 0, 0, 255), stroke_width=stroke_width, stroke_fill=(0, 0, 0, 255))
    canvas = Image.alpha_composite(canvas, extrude)

    text_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    td.text((ox, oy), text, font=f, fill=fill,
             stroke_width=stroke_width, stroke_fill=(0, 0, 0, 255))
    canvas = Image.alpha_composite(canvas, text_layer)
    # ox/tw describe the actual glyph's horizontal extent within the padded
    # canvas, same idea as oy/th vertically — callers use these to butt runs
    # up against each other tightly instead of stacking each run's full
    # extrude padding as visible gaps between words/emoji.
    return canvas, ox, oy, tw, th


def render_emoji_run(text, style):
    """Color emoji run via the system emoji font — no stroke/extrude (bitmap glyphs).

    Bitmap emoji fonts report metrics for the full glyph *cell*, which is
    much larger than the visible icon (generous built-in side-bearing, for
    line-height consistency in normal text) — trusting textbbox() for
    positioning left a large visible gap next to adjacent runs. Draw first,
    then measure the actual non-transparent pixels for the real ox/oy/tw/th.
    """
    ef = style["emoji_font"]
    stroke_width, extrude_depth = style["stroke_width"], style["extrude_depth"]
    probe = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    pd = ImageDraw.Draw(probe)
    bbox = pd.textbbox((0, 0), text, font=ef)
    cell_w, cell_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = extrude_depth + stroke_width + 10
    canvas = Image.new("RGBA", (cell_w + pad * 2, cell_h + pad * 2), (0, 0, 0, 0))
    draw_x, draw_y = pad - bbox[0], pad - bbox[1]
    d = ImageDraw.Draw(canvas)
    d.text((draw_x, draw_y), text, font=ef, embedded_color=True)

    alpha_bbox = canvas.getchannel("A").getbbox()
    if alpha_bbox is None:
        return canvas, draw_x, draw_y, cell_w, cell_h
    ox, oy = alpha_bbox[0], alpha_bbox[1]
    tw, th = alpha_bbox[2] - alpha_bbox[0], alpha_bbox[3] - alpha_bbox[1]
    return canvas, ox, oy, tw, th


# fixed horizontal gap (px, at FONT_SIZE=150 scale) between adjacent runs —
# tight like normal letter/word spacing, not the extrude-padding gap you'd
# get by just butting full canvases together. Secondary (smaller) style
# scales this down proportionally.
RUN_GAP = 14
RUN_GAP_SECONDARY = 7


def render_word_image(word, style, fill):
    """One word, possibly mixing Bebas Neue text and color emoji runs.

    Returns (canvas, left_ox, top_oy, content_w, content_h) — the actual
    glyph content bounds within canvas, found via a full-canvas alpha scan
    (same trick as render_emoji_run) so callers can butt words together
    tightly regardless of each run's own internal extrude/stroke padding.
    """
    run_gap = RUN_GAP if style is PRIMARY_STYLE else RUN_GAP_SECONDARY
    stroke_width, extrude_depth = style["stroke_width"], style["extrude_depth"]
    runs = split_runs(word)
    pieces = []
    for is_emoji, chunk in runs:
        if is_emoji:
            img, ox, oy, tw, th = render_emoji_run(chunk, style)
        else:
            img, ox, oy, tw, th = render_text_run(chunk, style, fill)
        pieces.append((img, ox, oy, tw, th))

    total_w = sum(p[3] for p in pieces) + run_gap * (len(pieces) - 1)
    max_h = max(p[0].height for p in pieces)

    margin = extrude_depth + stroke_width + 10
    canvas = Image.new("RGBA", (total_w + 2 * margin, max_h), (0, 0, 0, 0))
    content_x = margin
    for img, ox, oy, tw, th in pieces:
        y = (max_h - img.height) // 2
        paste_x = content_x - ox
        canvas.alpha_composite(img, (paste_x, y))
        content_x += tw + run_gap

    alpha_bbox = canvas.getchannel("A").getbbox()
    left_ox, top_oy = alpha_bbox[0], alpha_bbox[1]
    content_w, content_h = alpha_bbox[2] - alpha_bbox[0], alpha_bbox[3] - alpha_bbox[1]
    return canvas, left_ox, top_oy, content_w, content_h


def render_line_image(words, active_idx, style=PRIMARY_STYLE, fill_override=None):
    """One caption line built word-by-word so the currently-spoken word (at
    `active_idx`, or None) can be colored separately from the rest. `style`
    picks font size/stroke/base-color — PRIMARY_STYLE (white) or
    SECONDARY_STYLE (yellow, 50% size) for a simultaneous second speaker.
    `fill_override`, when given, replaces style's base_fill for every
    non-active word in the line — used for per-speaker caption coloring
    (see card["fill"] in compose_card)."""
    word_gap = style["word_gap"]
    base_fill = tuple(fill_override) if fill_override is not None else style["base_fill"]
    pieces = []
    for wi, word in enumerate(words):
        fill = HIGHLIGHT_GREEN if wi == active_idx else base_fill
        pieces.append(render_word_image(word, style, fill))

    total_w = sum(p[3] for p in pieces) + word_gap * (len(pieces) - 1)
    max_h = max(p[0].height for p in pieces)

    canvas = Image.new("RGBA", (total_w, max_h), (0, 0, 0, 0))
    content_x = 0
    adjusted_tops, adjusted_bottoms = [], []
    for img, left_ox, top_oy, content_w, content_h in pieces:
        y = (max_h - img.height) // 2
        paste_x = content_x - left_ox
        canvas.alpha_composite(img, (paste_x, y))
        adjusted_tops.append(top_oy + y)
        adjusted_bottoms.append(top_oy + y + content_h)
        content_x += content_w + word_gap

    top_oy = min(adjusted_tops)
    content_th = max(adjusted_bottoms) - top_oy
    return canvas, top_oy, content_th


def ease_out_back(t):
    if t >= 1.0:
        return 1.0
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


WORD_LEAD_S = 0.08  # small early lead so the highlight-swap doesn't read as late


def line_words(card, line_idx):
    """This card's words for one line, in order — falls back to splitting
    the plain 'lines' string (no highlight data) for older cards.json files
    that predate per-word timing."""
    if "words" in card:
        return [w["text"] for w in card["words"] if w["line"] == line_idx]
    if line_idx < len(card["lines"]):
        return card["lines"][line_idx].split(" ")
    return []


def active_word_index(card, t):
    """Global index into card['words'] of the word that should be
    highlighted at time t — sticky (stays on the last-started word until the
    next one's lead-adjusted start), so exactly one word is always active
    while the card is on screen."""
    words = card.get("words")
    if not words:
        return None
    adjusted = []
    floor = 0.0
    for w in words:
        s = max(w["start"] - WORD_LEAD_S, floor)
        adjusted.append(s)
        floor = s + 0.01
    active = 0
    for j, s in enumerate(adjusted):
        if t >= s:
            active = j
        else:
            break
    return active


def compose_card(card, t, style, cache):
    """Render one card's 1-2 lines onto a single transparent canvas, with the
    active word highlighted. Returns (block_img, top_center_y, bottom_edge_y):
    top_center_y is where the TOP line's glyph-center sits within block_img
    (the anchor callers align to BAR_CENTER_Y or a stacked position below
    it), bottom_edge_y is the block's lowest content pixel (for stacking a
    second block beneath this one).

    If the card carries a "fill" key (an [r,g,b,a] list), it overrides the
    style's base word color — used for per-speaker caption coloring on
    single-word cards, where there's no highlight-vs-rest distinction to
    preserve (green=Ben, yellow/red/blue=others, assigned by build_speaker_colors.py)."""
    fill_override = card.get("fill")

    def get_line_image(words, active_idx):
        key = (style["font"].size, tuple(words), active_idx, tuple(fill_override) if fill_override else None)
        if key not in cache:
            cache[key] = render_line_image(words, active_idx, style, fill_override)
        return cache[key]

    active_global = active_word_index(card, t)
    active_word = card["words"][active_global] if active_global is not None else None

    top_words = line_words(card, 0)
    top_active = None
    if active_word is not None and active_word["line"] == 0:
        top_active = [w["line"] for w in card["words"][:active_global + 1]].count(0) - 1
    top_img, top_oy, top_th = get_line_image(top_words, top_active)

    has_bottom = len(card["lines"]) > 1
    bottom_img = bottom_oy = bottom_th = None
    if has_bottom:
        bottom_words = line_words(card, 1)
        bottom_active = None
        if active_word is not None and active_word["line"] == 1:
            bottom_active = [w["line"] for w in card["words"][:active_global + 1]].count(1) - 1
        bottom_img, bottom_oy, bottom_th = get_line_image(bottom_words, bottom_active)

    gap_px = LINE_SPACING_FRAC * top_th if has_bottom else 0
    block_w = max(top_img.width, bottom_img.width if has_bottom else 0)
    top_paste_y = 0
    bottom_paste_y = int(top_paste_y + top_oy + top_th + gap_px - (bottom_oy or 0)) if has_bottom else None
    block_h = (bottom_paste_y + bottom_img.height) if has_bottom else top_img.height

    block = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    block.alpha_composite(top_img, ((block_w - top_img.width) // 2, top_paste_y))
    if has_bottom:
        block.alpha_composite(bottom_img, ((block_w - bottom_img.width) // 2, bottom_paste_y))

    top_center_y = top_paste_y + top_oy + top_th / 2
    bottom_edge_y = (bottom_paste_y + bottom_oy + bottom_th) if has_bottom else (top_paste_y + top_oy + top_th)
    return block, top_center_y, bottom_edge_y


def current_card(cards, ci_state, key, t):
    """Advance the (single, shared) index cursor for one card list and
    return the card active at time t, or None."""
    # The card on screen is the most recently STARTED one, if it hasn't
    # ended. When timings overlap (a word held long by the aligner, or hand
    # edits), the newer card replaces the older one and the older one never
    # comes back — same rule as the caption editor's preview, so what you
    # see there is what gets rendered.
    ci = ci_state[key]
    while ci + 1 < len(cards) and cards[ci + 1]["start"] <= t:
        ci += 1
    ci_state[key] = ci
    card = cards[ci] if cards[ci]["start"] <= t < cards[ci]["end"] else None
    return card


NOTE_RE = re.compile(r"\*([^*]*)\*")


def sanitize_cards(cards):
    """Editor notes (*like this*) are instructions, never caption text. The
    caption editor already keeps them out of "lines", but files saved by an
    older editor (or hand-edited) can still carry them inline — pull them out
    into card["note"] here so they can never be drawn. Also honors "|" as a
    line break. A card with no text AND no note is pointless and is dropped.
    A card with no text but a note is kept, text-less (a "silent" note-only
    card - draw_card skips it, so it shows nothing on its own, but its note
    still drives an image overlay, an fx, or a persisting text-position
    change exactly like a normal card's would; see main()'s render loop)."""
    kept = []
    for card in cards:
        notes = [card["note"]] if card.get("note") else []
        lines = []
        for line in card.get("lines", []):
            notes += [n.strip() for n in NOTE_RE.findall(line) if n.strip()]
            for part in NOTE_RE.sub(" ", line).split("|"):
                part = re.sub(r"\s+", " ", part).strip()
                if part:
                    lines.append(part)
        if not lines and not notes:
            continue
        card["lines"] = lines
        if notes:
            card["note"] = "; ".join(notes)
        kept.append(card)
    return kept


def fx_scale(fx, t, card):
    if not fx.get("scale_to"):
        return 1.0
    dur = max(card["end"] - card["start"], 0.05)
    u = min(1.0, max(0.0, (t - card["start"]) / dur))
    if fx.get("scale_fast"):
        u = 1 - (1 - min(1.0, u / 0.35)) ** 3  # punches to size in the first third
    return 1.0 + (fx["scale_to"] - 1.0) * u


def fx_shake(fx, t):
    """(dx, dy, angle_degrees) — deterministic in t, so re-renders are identical."""
    amp = fx.get("shake_px", 0)
    if not amp:
        return 0, 0, 0.0
    w = 2 * math.pi * fx.get("shake_hz", 24) * t
    dx = amp * (0.6 * math.sin(w) + 0.4 * math.sin(2.7 * w + 1.3))
    dy = amp * (0.6 * math.sin(1.31 * w + 0.7) + 0.4 * math.sin(3.1 * w + 2.1))
    angle = 0.1 * amp * math.sin(0.83 * w + 0.4) if amp >= 15 else 0.0  # big shakes also rock
    return int(round(dx)), int(round(dy)), angle


def fx_dance(fx, t, card):
    """A smooth vertical bob (distinct from shake's jitter) — deterministic
    in t relative to the card's own start, so it always begins at rest."""
    amp = fx.get("dance_px", 0)
    if not amp:
        return 0
    hz = fx.get("dance_hz", 2.2)
    u = t - card["start"]
    return int(round(amp * math.sin(2 * math.pi * hz * u)))


def fx_glow_alpha(fx, t, card):
    """0..1 opacity for a brief, dramatic flash: snaps in fast, fades across
    the rest of the card's time on screen."""
    if not fx.get("glow"):
        return 0.0
    u = t - card["start"]
    rise = 0.12
    if u < rise:
        return max(0.0, u / rise)
    dur = max(card["end"] - card["start"], 0.05)
    fade_dur = max(dur - rise, 0.05)
    return max(0.0, 1.0 - (u - rise) / fade_dur)


def make_glow(img, color, alpha):
    """A blurred, tinted silhouette of img's alpha shape, for compositing
    behind it as a radiant glow."""
    silhouette = Image.new("RGBA", img.size, (0, 0, 0, 0))
    silhouette.paste(Image.new("RGBA", img.size, tuple(color)), (0, 0), img.getchannel("A"))
    pad = 40
    canvas = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    canvas.alpha_composite(silhouette, (pad, pad))
    blurred = canvas.filter(ImageFilter.GaussianBlur(radius=18))
    r, g, b, a = blurred.split()
    a = a.point(lambda v: int(v * alpha))
    blurred.putalpha(a)
    return blurred


def load_cached_image(url, cache_dir):
    """The frames (+ per-frame duration in ms) of an image a note asked to
    overlay, IF it's already been downloaded to cache_dir under a hash of
    its URL — animated GIFs play back at their own timing, looped; a static
    image is just a 1-frame "animation". Never fetches it itself —
    downloading from an external site is a separate, explicit step — so a
    not-yet-cached URL just gets reported and skipped rather than blocking
    the render."""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    for ext in (".gif", ".webp", ".png", ".jpg", ".jpeg"):
        p = os.path.join(cache_dir, h + ext)
        if os.path.exists(p):
            im = Image.open(p)
            n_frames = getattr(im, "n_frames", 1)
            frames, durations = [], []
            for i in range(n_frames):
                im.seek(i)
                frames.append(im.convert("RGBA").copy())
                durations.append(max(im.info.get("duration", 100), 20))
            return frames, durations
    print(f'  image overlay requested but not fetched yet: {url}')
    print(f'    -> save it as {os.path.join(cache_dir, h + ".gif")} (or .png/.jpg/.webp) and re-render to include it')
    return None, None


def composite_clipped(frame, img, x, y):
    """alpha_composite that tolerates img hanging off the frame (shaken or
    zoomed captions can cross the edge)."""
    fx0, fy0 = max(x, 0), max(y, 0)
    fx1, fy1 = min(x + img.width, frame.width), min(y + img.height, frame.height)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    frame.alpha_composite(img.crop((fx0 - x, fy0 - y, fx1 - x, fy1 - y)), (fx0, fy0))


def split_lanes(raw):
    """Lane 0 is the main caption (big, at the seam); each further lane is a
    simultaneous caption drawn smaller beneath it (several speakers at once).
    A flat list assigns lanes from each card's "lane" (default 0, as saved by
    the caption editor); the older {"primary": [...], "secondary": [...]}
    form is lane 0 and lane 1."""
    if isinstance(raw, dict):
        lanes = [raw.get("primary", []), raw.get("secondary", [])]
    else:
        by_lane = {}
        for card in raw:
            by_lane.setdefault(max(0, int(card.get("lane", 0))), []).append(card)
        lanes = [by_lane.get(i, []) for i in range(max(by_lane) + 1)] if by_lane else [[]]
    return [sanitize_cards(sorted(cards, key=lambda c: c["start"])) for cards in lanes]


def draw_card(frame, card, style, t, cache, primary, base_y=None):
    """Draw one card (with its pop-in and any note effects). The main lane is
    anchored on the seam; a sub-lane stacks under base_y. Returns the y of the
    card's bottom edge so the next lane can stack beneath it."""
    cx = W // 2
    progress = ease_out_back(min(1.0, (t - card["start"]) / POP_DURATION))
    scale = (0.55 + 0.45 * progress) * card.get("emphasis_scale", 1.0)
    fx = card.get("_fx") or {}
    dx = dy = 0
    angle = 0.0
    if fx:
        scale *= fx_scale(fx, t, card)
        dx, dy, angle = fx_shake(fx, t)
        dy += fx_dance(fx, t, card)
    block, top_center_y, bottom_edge_y = compose_card(card, t, style, cache)
    nw = max(1, int(block.width * scale))
    nh = max(1, int(block.height * scale))
    resized = block.resize((nw, nh), Image.LANCZOS)
    if primary:
        anchor_y = card.get("_anchor_y", BAR_CENTER_Y)
        canvas_y = int(anchor_y - top_center_y * scale)
    else:
        canvas_y = int(base_y + SECONDARY_GAP_FRAC * FONT_SIZE_SECONDARY * scale)
    paste_x, paste_y = cx - nw // 2, canvas_y
    if angle:
        resized = resized.rotate(angle, resample=Image.BICUBIC, expand=True)
        paste_x -= (resized.width - nw) // 2
        paste_y -= (resized.height - nh) // 2
    if fx.get("glow"):
        glow_a = fx_glow_alpha(fx, t, card)
        if glow_a > 0.01:
            glow_img = make_glow(resized, fx.get("color") or (255, 248, 210, 255), glow_a)
            gx = paste_x - (glow_img.width - resized.width) // 2
            gy = paste_y - (glow_img.height - resized.height) // 2
            composite_clipped(frame, glow_img, gx + dx, gy + dy)
    composite_clipped(frame, resized, paste_x + dx, paste_y + dy)
    return canvas_y + bottom_edge_y * scale


RAMPABLE_KEYS = ("shake_px", "scale_to", "dance_px")


def apply_fx_passes(cards, lane_no):
    """Three passes over one lane's cards, each layered on the last:
    1. each card's own note -> fx (or its explicit "fx" dict, unchanged).
    2. "make all instances of "X" do a <effect>" notes apply that effect to
       every card in the lane whose text is one of the named words, anywhere
       in the timeline — not just cards after the instruction.
    3. a progressively/gradually/increasingly note ramps its effect linearly
       across itself and every contiguous following card that shares the
       same effect key, peaking at the strongest intensity word found
       anywhere in that run.
    Then applies any note-driven color override to card["fill"], and logs
    each note's final, resolved effect."""
    for card in cards:
        card["_fx"] = dict(card.get("fx") or fx_from_note(card.get("note")))

    for card in cards:
        parsed = parse_global_instruction(card.get("note"))
        if not parsed:
            continue
        targets, effect_note = parsed
        target_fx = fx_from_note(effect_note)
        if not target_fx:
            continue
        target_set = set(targets)
        for other in cards:
            text_words = set(re.findall(r"[a-z']+", " ".join(other.get("lines", [])).lower()))
            if text_words & target_set:
                merged = dict(target_fx)
                merged.update(other["_fx"])  # that card's own note wins on shared keys
                other["_fx"] = merged

    for i, card in enumerate(cards):
        if not is_ramp_trigger(card.get("note")):
            continue
        keys = [k for k in RAMPABLE_KEYS if card["_fx"].get(k)]
        if not keys:
            continue
        group = [card]
        j = i + 1
        while j < len(cards):
            nxt = cards[j]
            if nxt["start"] - group[-1]["end"] > 1.0 or not all(nxt["_fx"].get(k) for k in keys):
                break
            group.append(nxt)
            j += 1
        if len(group) < 2:
            continue
        start_factor = note_factor(card.get("note"))
        end_factor = max((note_factor(c.get("note")) for c in group), default=start_factor)
        if end_factor <= start_factor:
            end_factor = min(start_factor * 1.5, MAX_FACTOR)
        ratio = end_factor / start_factor if start_factor else 1.0
        n = len(group)
        for k in keys:
            start_val = group[0]["_fx"][k]
            end_val = 1.0 + (start_val - 1.0) * ratio if k == "scale_to" else start_val * ratio
            for gi, gcard in enumerate(group):
                gcard["_fx"][k] = start_val + (end_val - start_val) * (gi / (n - 1))

    # Persisting text-position toggle: carries the last-seen anchor forward
    # onto every following card, same as an editor expecting "put everything
    # from here down lower" to stick until told otherwise. Lane 0 only - the
    # big primary caption is the one that ever sits over a full-facecam
    # subject's face; a secondary lane always stacks beneath whatever primary
    # is showing (or BAR_CENTER_Y as a fallback), so it follows automatically.
    if lane_no == 0:
        current_anchor = BAR_CENTER_Y
        for card in cards:
            pos = parse_text_position(card.get("note"))
            if pos == "bottom":
                current_anchor = TEXT_ANCHOR_BOTTOM
            elif pos == "default":
                current_anchor = BAR_CENTER_Y
            card["_anchor_y"] = current_anchor

    for card in cards:
        if card["_fx"].get("color"):
            card["fill"] = list(card["_fx"]["color"])
        if card.get("note"):
            pos = parse_text_position(card["note"])
            fx = card["_fx"]
            if not fx and pos:
                msg = f'text position -> {pos} <- "{card["note"]}"'
            else:
                msg = describe(card["note"], fx)
                if pos:
                    msg += f'; text position -> {pos}'
            print(f'  note (lane {lane_no + 1}) @ {card["start"]:.2f}s: {msg}')


def gather_image_overlays(lanes, cards_path, duration_s):
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(cards_path)), "note_images")
    overlays = []
    cache = {}  # url -> (resized_frames, durations, total_ms), computed once per URL
    for cards in lanes:
        for card in cards:
            fx = card["_fx"]
            url = fx.get("image_url")
            if not url:
                continue
            if url not in cache:
                os.makedirs(cache_dir, exist_ok=True)
                frames, durations = load_cached_image(url, cache_dir)
                if frames is not None:
                    target_w = int(W * 0.55)
                    resized = [f.resize((target_w, int(f.height * target_w / f.width)), Image.LANCZOS) for f in frames]
                    cache[url] = (resized, durations, sum(durations))
                else:
                    cache[url] = None
            entry = cache[url]
            if entry is None:
                continue
            frames, durations, total_ms = entry
            start = card["start"]
            if fx["image_duration"] == "end":
                end = duration_s
            elif fx["image_duration"] == "card":
                end = min(duration_s, card["end"])
            else:
                end = min(duration_s, start + fx["image_duration"])
            overlays.append({
                "start": start, "end": end, "frames": frames, "durations": durations,
                "total_ms": total_ms, "position": fx["image_position"],
            })
    return overlays


def draw_image_overlay(frame, ov, t):
    frames = ov["frames"]
    if len(frames) == 1:
        img = frames[0]
    else:
        elapsed_ms = ((t - ov["start"]) * 1000.0) % ov["total_ms"]
        acc = 0.0
        img = frames[-1]
        for f, d in zip(frames, ov["durations"]):
            acc += d
            if elapsed_ms < acc:
                img = f
                break
    pos = ov["position"]
    if isinstance(pos, tuple):
        # absolute (vertical, horizontal) grid anchor on the full frame
        v, h, margin = pos[0], pos[1], 24
        ox = margin if h == "left" else W - img.width - margin if h == "right" else (W - img.width) // 2
        oy = margin if v == "top" else H - img.height - margin if v == "bottom" else (H - img.height) // 2
    else:
        # legacy: relative to the caption bar
        ox = (W - img.width) // 2
        oy = BAR_CENTER_Y + 260 if pos == "below" else BAR_CENTER_Y - 260 - img.height
    composite_clipped(frame, img, ox, oy)


def main():
    cards_path, duration_s, out_path = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    font_choice = find_font_choice(cards_path)
    apply_font_choice(font_choice)
    print(f"  font: {font_choice}")
    lanes = split_lanes(json.load(open(cards_path, encoding="utf-8")))
    for li, cards in enumerate(lanes):
        apply_fx_passes(cards, li)
    if len(lanes) > 1:
        print(f"  {len(lanes)} simultaneous lanes: " + ", ".join(str(len(c)) for c in lanes) + " cards")
    image_overlays = gather_image_overlays(lanes, cards_path, duration_s)
    total_frames = int(round(duration_s * FPS))

    cache = {}
    ci_state = {i: 0 for i in range(len(lanes))}

    ff = subprocess.Popen([
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
        "-alpha_bits", "8", out_path, "-loglevel", "warning",
    ], stdin=subprocess.PIPE)

    for fi in range(total_frames):
        t = fi / FPS
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        bottom = None  # bottom edge of the last lane drawn; sub-lanes stack under it
        for li, cards in enumerate(lanes):
            card = current_card(cards, ci_state, li, t) if cards else None
            if card is None or not card["lines"]:
                continue  # a silent note-only card (see sanitize_cards) draws nothing
            if li == 0:
                bottom = draw_card(frame, card, PRIMARY_STYLE, t, cache, primary=True)
            else:
                # stack below whatever is showing above it, else on the seam
                base = bottom if bottom is not None else BAR_CENTER_Y
                bottom = draw_card(frame, card, SECONDARY_STYLE, t, cache, primary=False, base_y=base)

        for ov in image_overlays:
            if ov["start"] <= t < ov["end"]:
                draw_image_overlay(frame, ov, t)

        frame_bytes = frame.tobytes()
        ff.stdin.write(frame_bytes)
        if fi % 300 == 0:
            print(f"frame {fi}/{total_frames}")

    ff.stdin.close()
    ff.wait()
    print("wrote", out_path)


if __name__ == "__main__":
    main()
