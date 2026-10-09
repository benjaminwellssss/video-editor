"""Deliberately bad 'photoshop' merge of the two covers for the DISTORT THE DCC mashup."""
import io
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

DCC, DLB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
random.seed(7)
FONTS = os.path.join(os.environ.get("WINDIR", ""), "Fonts")  # Windows font folder
S = 3000
k = S / 2048  # the DCC cover reference coords below are on a 2048 grid

bg = Image.open(DLB).convert("RGB").resize((S, S))
dcc = Image.open(DCC).convert("RGB").resize((S, S))

# 1. Sloppy lasso cut of the DCC building, with chunks of red sky left on the edges.
lasso = [(0, 1180), (200, 1050), (600, 960), (900, 900), (1080, 780), (1130, 690), (1190, 700),
         (1175, 860), (1260, 850), (1360, 870), (1430, 950), (1460, 1060), (1620, 1110),
         (1820, 1190), (2048, 1260), (2048, 2048), (0, 2048)]
pts = []
for (x0, y0), (x1, y1) in zip(lasso, lasso[1:] + lasso[:1]):
    for t in [i / 6 for i in range(6)]:
        pts.append(((x0 + (x1 - x0) * t) * k + random.randint(-45, 45),
                    (y0 + (y1 - y0) * t) * k + random.randint(-45, 45)))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).polygon(pts, fill=255)
building = Image.new("RGBA", (S, S))
building.paste(dcc, mask=mask)
# white "selection fringe" around the cutout, the classic tell
fringe = mask.filter(ImageFilter.MaxFilter(25))
halo = Image.new("RGBA", (S, S), (255, 255, 255, 0))
halo.putalpha(fringe.point(lambda v: 230 if v else 0))
building = Image.alpha_composite(halo, building)
building = building.rotate(-4, resample=Image.BICUBIC, expand=False).resize((int(S * 1.02), int(S * 0.8)))
bg.paste(building, (-40, int(S * 0.2)), building)

# 2. The tiny Bastille swimmer, rectangle-selected (background box and all), blown up 3x,
#    JPEG-crunched so it doesn't match anything around it.
src = Image.open(DLB).convert("RGB").resize((S, S))
diver = src.crop((1300, 1400, 1700, 1640))
buf = io.BytesIO()
diver.resize((diver.width // 3, diver.height // 3)).save(buf, "JPEG", quality=8)
diver = Image.open(buf).resize((diver.width * 3, diver.height * 3), Image.NEAREST)
diver = diver.rotate(18, expand=True, fillcolor=(255, 255, 255))
bg.paste(diver, (1700, 1150))

# 3. The DCC logo text stretched sideways off the original cover.
title = dcc.crop((int(400 * k), int(280 * k), int(1060 * k), int(450 * k)))
title = title.resize((int(title.width * 1.6), int(title.height * 0.7)))
bg.paste(title, (40, 2600))

# 4. WordArt title: rainbow gradient, fat outline, hard drop shadow, crooked.
font = ImageFont.truetype(os.path.join(FONTS, "impact.ttf"), 430)
text = "DISTORT THE DCC"
layer = Image.new("RGBA", (S + 800, 700), (0, 0, 0, 0))
d = ImageDraw.Draw(layer)
d.text((60 + 40, 60 + 40), text, font=font, fill=(0, 0, 0, 255))  # drop shadow
d.text((60, 60), text, font=font, fill=(255, 255, 255, 255), stroke_width=22, stroke_fill=(20, 0, 120, 255))
m = Image.new("L", layer.size, 0)
ImageDraw.Draw(m).text((60, 60), text, font=font, fill=255)
grad = Image.linear_gradient("L").rotate(90).resize(layer.size)
rainbow = ImageOps.colorize(grad, black=(255, 0, 80), white=(255, 230, 0), mid=(0, 255, 140))
layer.paste(rainbow, (0, 0), m)
layer = layer.rotate(7, expand=True, resample=Image.BICUBIC)
layer = layer.resize((int(S * 0.98), int(layer.height * (S * 0.98) / layer.width * 1.15)))
bg.paste(layer, (20, 120), layer)

# 5. Comic Sans credit with a highlighter box, plus a lens flare nobody asked for.
small = ImageFont.truetype(os.path.join(FONTS, "comicbd.ttf"), 120)
d = ImageDraw.Draw(bg)
credit = "nothing but thieves x bastille"
w = d.textlength(credit, font=small)
d.rectangle((S - w - 140, 900, S - 60, 1060), fill=(255, 255, 0))
d.text((S - w - 100, 915), credit, font=small, fill=(255, 0, 255))
flare = Image.new("RGBA", (S, S), (0, 0, 0, 0))
fd = ImageDraw.Draw(flare)
cx, cy = 1500, 1430
for r, a in [(260, 70), (150, 120), (60, 230)]:
    fd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 230, a))
for i, (r, c) in enumerate([(90, (120, 255, 200, 90)), (50, (255, 120, 255, 110)), (140, (120, 160, 255, 60))]):
    px, py = cx - (i + 1) * 420, cy + (i + 1) * 300
    fd.ellipse((px - r, py - r, px + r, py + r), fill=c)
bg = Image.alpha_composite(bg.convert("RGBA"), flare.filter(ImageFilter.GaussianBlur(18))).convert("RGB")

bg.save(OUT, quality=92)
print(OUT, bg.size)
