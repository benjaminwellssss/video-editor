"""Render a black-screen text disclaimer card as a standalone opaque video
clip (1920x1080), meant to be prepended to a Resolve timeline as its own
clip (never composited/overlaid — it IS the frame, full black, no video
underneath).

Usage: render_disclaimer_card.py <text> <duration_s> <out.mp4>

Word-wraps <text> centered on a black background, white Arial/Helvetica
text (falls back to Arial if Helvetica isn't installed - it isn't on
Windows by default). A trailing emoji (if the text ends with one) is drawn
with the system color-emoji font, same stitching trick as render_captions.py,
since Arial has no emoji glyphs.
"""
import re
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FPS = 30
FONT_SIZE = 64
LINE_GAP = 20
MAX_TEXT_WIDTH = 1500

FONT_PATH = r"C:\Windows\Fonts\Helvetica.ttf"
try:
    ImageFont.truetype(FONT_PATH, FONT_SIZE)
except OSError:
    FONT_PATH = r"C:\Windows\Fonts\arial.ttf"  # Helvetica isn't bundled with Windows
EMOJI_FONT_PATH = r"C:\Windows\Fonts\seguiemj.ttf"

EMOJI_RE = re.compile(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+$")


def wrap_text(text, font, max_width, draw):
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_line(text, font, emoji_font):
    """One line, as text + an optional trailing emoji run stitched on."""
    m = EMOJI_RE.search(text)
    plain, emoji = (text[: m.start()].rstrip(), m.group(0)) if m else (text, "")

    probe = Image.new("RGBA", (10, 10))
    pd = ImageDraw.Draw(probe)
    pbbox = pd.textbbox((0, 0), plain, font=font) if plain else (0, 0, 0, 0)
    pw, ph = pbbox[2] - pbbox[0], pbbox[3] - pbbox[1]

    ew = eh = 0
    if emoji:
        ebbox = pd.textbbox((0, 0), emoji, font=emoji_font)
        ew, eh = ebbox[2] - ebbox[0], ebbox[3] - ebbox[1]

    gap = 14 if (plain and emoji) else 0
    total_w = pw + gap + ew
    total_h = max(ph, eh)
    canvas = Image.new("RGBA", (total_w + 4, total_h + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    x = -pbbox[0]
    if plain:
        y = -pbbox[1] + (total_h - ph)
        d.text((x, y), plain, font=font, fill=(255, 255, 255, 255))
        x += pw + gap
    if emoji:
        ey = -ebbox[1] + (total_h - eh)
        d.text((x - ebbox[0], ey), emoji, font=emoji_font, embedded_color=True)
    return canvas


def main():
    text, duration_s, out_path = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, FONT_SIZE)

    probe = Image.new("RGBA", (10, 10))
    pd = ImageDraw.Draw(probe)
    lines = wrap_text(text, font, MAX_TEXT_WIDTH, pd)
    line_imgs = [render_line(line, font, emoji_font) for line in lines]

    block_h = sum(im.height for im in line_imgs) + LINE_GAP * (len(line_imgs) - 1)
    frame = Image.new("RGB", (W, H), (0, 0, 0))
    y = (H - block_h) // 2
    for im in line_imgs:
        x = (W - im.width) // 2
        frame.paste(im, (x, y), im)
        y += im.height + LINE_GAP

    total_frames = int(round(duration_s * FPS))
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12",
        out_path, "-loglevel", "warning",
    ], stdin=subprocess.PIPE)

    frame_bytes = frame.tobytes()
    for _ in range(total_frames):
        ff.stdin.write(frame_bytes)
    ff.stdin.close()
    ff.wait()
    print("wrote", out_path, f"({duration_s}s, font={FONT_PATH})")


if __name__ == "__main__":
    main()
