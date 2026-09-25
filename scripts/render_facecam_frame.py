"""Render the retro "facecam.exe" window-chrome frame (matching
overlay_facecam.html's design - see E:\\Streaming\\Overlays + Images\\overlay_facecam.html)
as a transparent PNG overlay, sized around a given video content box.

Usage: <python> render_facecam_frame.py <content_w> <content_h> <out_path>

The returned frame has a fully transparent cutout of exactly (content_w,
content_h) where the live facecam video shows through; composite the video
first, then this frame on top, both anchored at the same top-left point
(the cutout's offset within the frame is printed to stdout).
"""
import sys
from PIL import Image, ImageDraw, ImageFont

WIN_GRAY = (192, 192, 192, 255)
WIN_GRAY_DARK = (128, 128, 128, 255)
WIN_GRAY_DARKER = (64, 64, 64, 255)
WIN_WHITE = (255, 255, 255, 255)
WIN_BLUE_TITLE = (0, 0, 128, 255)
WIN_BLUE_TITLE_LIGHT = (16, 132, 208, 255)
WIN_BLACK = (0, 0, 0, 255)
RED = (220, 30, 30, 255)

FONT_PATH = r"C:\Windows\Fonts\tahoma.ttf"
FONT_BOLD_PATH = r"C:\Windows\Fonts\tahomabd.ttf"


def hgrad(draw, box, c1, c2):
    x0, y0, x1, y1 = box
    w = x1 - x0
    for i in range(w):
        t = i / max(w - 1, 1)
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.line([(x0 + i, y0), (x0 + i, y1)], fill=(r, g, b, 255))


def main():
    content_w, content_h = int(sys.argv[1]), int(sys.argv[2])
    out_path = sys.argv[3]

    scale = content_w / 446.0  # CSS's ~446px-wide cutout reference
    border = max(2, round(2 * scale))
    pad = max(2, round(3 * scale))
    titlebar_h = max(18, round(26 * scale))
    statusbar_h = max(14, round(20 * scale))
    margin = max(2, round(3 * scale))

    body_w = content_w + 2 * border
    win_w = body_w + 2 * pad
    win_h = titlebar_h + pad + body_w * 0 + (content_h + 2 * border) + pad + statusbar_h + border * 2
    canvas_w = win_w + 2 * margin
    canvas_h = win_h + 2 * margin

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    wx0, wy0 = margin, margin
    wx1, wy1 = wx0 + win_w, wy0 + win_h
    d.rectangle([wx0, wy0, wx1, wy1], fill=WIN_GRAY)
    d.line([(wx0, wy0), (wx1, wy0)], fill=WIN_WHITE, width=border)
    d.line([(wx0, wy0), (wx0, wy1)], fill=WIN_WHITE, width=border)
    d.line([(wx1, wy0), (wx1, wy1)], fill=WIN_BLACK, width=border)
    d.line([(wx0, wy1), (wx1, wy1)], fill=WIN_BLACK, width=border)

    tb_x0, tb_y0 = wx0 + pad, wy0 + pad
    tb_x1, tb_y1 = wx1 - pad, tb_y0 + titlebar_h
    hgrad(d, (tb_x0, tb_y0, tb_x1, tb_y1), WIN_BLUE_TITLE, WIN_BLUE_TITLE_LIGHT)

    try:
        title_font = ImageFont.truetype(FONT_BOLD_PATH, max(11, round(13 * scale)))
        icon_font = ImageFont.truetype(FONT_PATH, max(10, round(11 * scale)))
    except OSError:
        title_font = icon_font = ImageFont.load_default()

    icon_sz = max(12, round(16 * scale))
    icon_x0, icon_y0 = tb_x0 + round(3 * scale), tb_y0 + (titlebar_h - icon_sz) // 2
    d.rectangle([icon_x0, icon_y0, icon_x0 + icon_sz, icon_y0 + icon_sz], fill=WIN_GRAY, outline=WIN_BLACK)
    d.text((icon_x0 + icon_sz // 2, icon_y0 + icon_sz // 2), "\U0001F3A5", font=icon_font, fill=WIN_BLACK, anchor="mm")

    title_x = icon_x0 + icon_sz + round(6 * scale)
    d.text((title_x, tb_y0 + titlebar_h // 2), "facecam.exe", font=title_font, fill=WIN_WHITE, anchor="lm")

    btn_sz_w, btn_sz_h = round(18 * scale), round(16 * scale)
    btn_gap = round(2 * scale)
    btn_y0 = tb_y0 + (titlebar_h - btn_sz_h) // 2
    btn_x1 = tb_x1 - round(3 * scale)
    for label in ("\u2715", "\u25a1", "_"):
        bx0 = btn_x1 - btn_sz_w
        d.rectangle([bx0, btn_y0, bx0 + btn_sz_w, btn_y0 + btn_sz_h], fill=WIN_GRAY)
        d.line([(bx0, btn_y0), (bx0 + btn_sz_w, btn_y0)], fill=WIN_WHITE, width=1)
        d.line([(bx0, btn_y0), (bx0, btn_y0 + btn_sz_h)], fill=WIN_WHITE, width=1)
        d.line([(bx0 + btn_sz_w, btn_y0), (bx0 + btn_sz_w, btn_y0 + btn_sz_h)], fill=WIN_BLACK, width=1)
        d.line([(bx0, btn_y0 + btn_sz_h), (bx0 + btn_sz_w, btn_y0 + btn_sz_h)], fill=WIN_BLACK, width=1)
        d.text((bx0 + btn_sz_w // 2, btn_y0 + btn_sz_h // 2), label, font=icon_font, fill=WIN_BLACK, anchor="mm")
        btn_x1 = bx0 - btn_gap

    body_x0, body_y0 = tb_x0, tb_y1 + round(3 * scale)
    body_x1, body_y1 = tb_x1, body_y0 + content_h + 2 * border
    d.rectangle([body_x0, body_y0, body_x1, body_y1], fill=WIN_BLACK)
    d.line([(body_x0, body_y0), (body_x1, body_y0)], fill=WIN_GRAY_DARKER, width=border)
    d.line([(body_x0, body_y0), (body_x0, body_y1)], fill=WIN_GRAY_DARKER, width=border)
    d.line([(body_x1, body_y0), (body_x1, body_y1)], fill=WIN_WHITE, width=border)
    d.line([(body_x0, body_y1), (body_x1, body_y1)], fill=WIN_WHITE, width=border)

    cutout_x0, cutout_y0 = body_x0 + border, body_y0 + border
    d.rectangle([cutout_x0, cutout_y0, cutout_x0 + content_w, cutout_y0 + content_h], fill=(0, 0, 0, 0))

    sb_x0, sb_y0 = body_x0, body_y1 + round(3 * scale)
    sb_x1, sb_y1 = body_x1, sb_y0 + statusbar_h
    d.rectangle([sb_x0, sb_y0, sb_x1, sb_y1], fill=WIN_GRAY, outline=WIN_GRAY_DARK)

    dot_sz = max(5, round(8 * scale))
    dot_x0, dot_y0 = sb_x0 + round(6 * scale), sb_y0 + (statusbar_h - dot_sz) // 2
    d.ellipse([dot_x0, dot_y0, dot_x0 + dot_sz, dot_y0 + dot_sz], fill=RED)
    live_font = ImageFont.truetype(FONT_PATH, max(9, round(11 * scale))) if title_font else ImageFont.load_default()
    d.text((dot_x0 + dot_sz + round(4 * scale), sb_y0 + statusbar_h // 2), "LIVE", font=live_font, fill=WIN_BLACK, anchor="lm")
    d.text((sb_x1 - round(6 * scale), sb_y0 + statusbar_h // 2), "00:00:00", font=live_font, fill=WIN_BLACK, anchor="rm")

    img.save(out_path)
    print(f"wrote {out_path} ({canvas_w}x{canvas_h}), cutout at ({cutout_x0},{cutout_y0}) size {content_w}x{content_h}")


if __name__ == "__main__":
    main()
