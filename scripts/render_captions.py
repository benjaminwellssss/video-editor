"""Render animated pop-in captions (up to 2 lines x 2 words) as a transparent overlay video.

Usage: <venv-python> render_captions.py <cards.json> <duration_s> <out.mov>

cards.json is either:
  - a flat list of {"start", "end", "lines", "words"?} (single-speaker, as before), or
  - {"primary": [...same card shape...], "secondary": [...same card shape...]}
    for multi-speaker jobs — "secondary" cards render as a smaller (50%),
    yellow-base second caption row beneath whichever primary card is showing,
    for moments where a second speaker talks over the first. Both lists use
    word-level "speaker"-turn card breaks (see build_speaker_cards.py) so at
    most one speaker's text is ever in a given card.
"""
import json
import re
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FPS = 30
FONT_PATH = r"C:\Users\Bem\Desktop\video-editor\assets\fonts\BebasNeue-Regular.ttf"
EMOJI_FONT_PATH = r"C:\Windows\Fonts\seguiemj.ttf"
FONT_SIZE = 150
FONT_SIZE_SECONDARY = 75  # 50% size, matching render_handle.py's established scale-down
BAR_CENTER_Y = 660  # seam between facecam and gameplay (overlap-fixed layout, no visible bar anymore)
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

font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, FONT_SIZE)
font_secondary = ImageFont.truetype(FONT_PATH, FONT_SIZE_SECONDARY)
emoji_font_secondary = ImageFont.truetype(EMOJI_FONT_PATH, FONT_SIZE_SECONDARY)

# A "style" bundles everything that scales together between the primary and
# secondary caption rows, so the render_* functions don't need two copies.
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


def render_line_image(words, active_idx, style=PRIMARY_STYLE):
    """One caption line built word-by-word so the currently-spoken word (at
    `active_idx`, or None) can be colored separately from the rest. `style`
    picks font size/stroke/base-color — PRIMARY_STYLE (white) or
    SECONDARY_STYLE (yellow, 50% size) for a simultaneous second speaker."""
    word_gap = style["word_gap"]
    base_fill = style["base_fill"]
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
    second block beneath this one)."""
    def get_line_image(words, active_idx):
        key = (style["font"].size, tuple(words), active_idx)
        if key not in cache:
            cache[key] = render_line_image(words, active_idx, style)
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
    ci = ci_state[key]
    while ci < len(cards) - 1 and t >= cards[ci]["end"]:
        ci += 1
    ci_state[key] = ci
    card = cards[ci] if cards[ci]["start"] <= t < cards[ci]["end"] else None
    return card


def main():
    cards_path, duration_s, out_path = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    raw = json.load(open(cards_path, encoding="utf-8"))
    if isinstance(raw, dict):
        primary_cards = raw.get("primary", [])
        secondary_cards = raw.get("secondary", [])
    else:
        primary_cards, secondary_cards = raw, []
    total_frames = int(round(duration_s * FPS))

    cache = {}
    ci_state = {"primary": 0, "secondary": 0}

    ff = subprocess.Popen([
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
        "-alpha_bits", "8", out_path, "-loglevel", "warning",
    ], stdin=subprocess.PIPE)

    for fi in range(total_frames):
        t = fi / FPS
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        cx = W // 2

        primary_bottom_in_frame = None
        card = current_card(primary_cards, ci_state, "primary", t) if primary_cards else None
        if card is not None:
            progress = ease_out_back(min(1.0, (t - card["start"]) / POP_DURATION))
            scale = (0.55 + 0.45 * progress) * card.get("emphasis_scale", 1.0)
            block, top_center_y, bottom_edge_y = compose_card(card, t, PRIMARY_STYLE, cache)
            nw = max(1, int(block.width * scale))
            nh = max(1, int(block.height * scale))
            resized = block.resize((nw, nh), Image.LANCZOS)
            canvas_y = int(BAR_CENTER_Y - top_center_y * scale)
            frame.alpha_composite(resized, (cx - nw // 2, canvas_y))
            primary_bottom_in_frame = canvas_y + bottom_edge_y * scale

        sec_card = current_card(secondary_cards, ci_state, "secondary", t) if secondary_cards else None
        if sec_card is not None:
            progress = ease_out_back(min(1.0, (t - sec_card["start"]) / POP_DURATION))
            scale = 0.55 + 0.45 * progress
            block, top_center_y, bottom_edge_y = compose_card(sec_card, t, SECONDARY_STYLE, cache)
            nw = max(1, int(block.width * scale))
            nh = max(1, int(block.height * scale))
            resized = block.resize((nw, nh), Image.LANCZOS)
            # stack below the primary block if one is showing this frame,
            # else anchor to the same seam the primary block would use
            base_y = primary_bottom_in_frame if primary_bottom_in_frame is not None else BAR_CENTER_Y
            gap_px = SECONDARY_GAP_FRAC * FONT_SIZE_SECONDARY * scale
            canvas_y = int(base_y + gap_px)
            frame.alpha_composite(resized, (cx - nw // 2, canvas_y))

        frame_bytes = frame.tobytes()
        ff.stdin.write(frame_bytes)
        if fi % 300 == 0:
            print(f"frame {fi}/{total_frames}")

    ff.stdin.close()
    ff.wait()
    print("wrote", out_path)


if __name__ == "__main__":
    main()
