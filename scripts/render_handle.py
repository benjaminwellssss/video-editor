"""Render a static handle/watermark PNG (transparent) in the caption font/style
at 50% the caption font size, for the empty headroom above the facecam.

Usage: render_handle.py <text> <out.png>
"""
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FONT_PATH = r"C:\Users\Bem\Desktop\video-editor\assets\fonts\BebasNeue-Regular.ttf"
FONT_SIZE = 75  # 50% of the 150px caption font
STROKE_WIDTH = 4  # roughly half of the caption's 7px stroke
TOP_Y = 55  # top margin within the facecam headroom
LEFT_X = 45  # left margin

# Left-aligned, not centered: a phone's "Dynamic Island" (or any front-camera
# cutout) sits horizontally centered at the very top of the screen, so a
# centered top handle gets covered when a viewer watches fullscreen on an
# iPhone. Left corners are clear on every device regardless of exact
# vertical safe-zone height, so that's the fix rather than guessing a
# below-the-island Y offset that would vary per device/app.


def main():
    text, out_path = sys.argv[1], sys.argv[2]
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(frame)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=STROKE_WIDTH)
    x = LEFT_X - bbox[0]
    y = TOP_Y - bbox[1]
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255),
            stroke_width=STROKE_WIDTH, stroke_fill=(0, 0, 0, 255))

    frame.save(out_path)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
