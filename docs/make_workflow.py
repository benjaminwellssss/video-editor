"""Generate docs/workflow.svg (flowchart of the pipeline with its options).

PNG: chrome --headless=new --window-size=1500,1830 --screenshot=docs/workflow.png docs/workflow.svg
"""
import os
from html import escape

W, H = 1500, 1830
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
C = {
    "auto": ("#e8f1ff", "#3b6fd8"),     # automated step (Claude + scripts)
    "manual": ("#fff1df", "#e08a1e"),   # your hands-on step
    "choice": ("#f3e8ff", "#8a4fd6"),   # decision
    "out": ("#e5f7ea", "#2f9e57"),      # deliverable folder
    "start": ("#2b2f3a", "#2b2f3a"),
}
out = []


def box(cx, y, w, lines, kind="auto", h=None, dashed=False):
    fill, stroke = C[kind]
    lh = 19
    h = h or 22 + lh * len(lines)
    x = cx - w / 2
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    r = h / 2 if kind == "out" else 10
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')
    ty = y + 11 + lh * 0.8
    for i, ln in enumerate(lines):
        bold = i == 0
        color = "#ffffff" if kind == "start" else ("#1d2330" if bold else "#4a5263")
        size = 15 if bold else 13
        weight = "700" if bold else "400"
        out.append(f'<text x="{cx}" y="{ty + i * lh}" text-anchor="middle" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(ln)}</text>')
    return y + h


def diamond(cx, cy, w, h, lines):
    fill, stroke = C["choice"]
    pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
    out.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    y0 = cy - (len(lines) - 1) * 9 + 5
    for i, ln in enumerate(lines):
        out.append(f'<text x="{cx}" y="{y0 + i * 18}" text-anchor="middle" font-size="{15 if i == 0 else 13}" font-weight="{700 if i == 0 else 400}" fill="#1d2330">{escape(ln)}</text>')
    return cy + h / 2


def arrow(points, label=None, lx=None, ly=None, dashed=False):
    d = "M " + " L ".join(f"{x},{y}" for x, y in points)
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    out.append(f'<path d="{d}" fill="none" stroke="#6b7385" stroke-width="2"{dash} marker-end="url(#ah)"/>')
    if label:
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="13" font-weight="700" fill="#8a4fd6">{escape(label)}</text>')


# ---- trunk -------------------------------------------------------------------
TX = W / 2
out.append(f'<text x="{TX}" y="40" text-anchor="middle" font-size="26" font-weight="800" fill="#1d2330">Stream → finished videos: the workflow</text>')
out.append(f'<text x="{TX}" y="64" text-anchor="middle" font-size="14" fill="#4a5263">Every job starts at the top; step 3 picks one or more branches.</text>')

y = box(TX, 86, 380, ["Raw stream recording", "OBS, multi-track audio, optional OBS markers"], "start")
arrow([(TX, y), (TX, y + 26)])
y = box(TX, y + 28, 520, ["1 · Intake + audio-track check",
                          "copy raw into projects/<job>/raw · sample every track at 2–3 spots",
                          "you confirm which track is the voice before anything is built"], "manual")
arrow([(TX, y), (TX, y + 26)])
y = box(TX, y + 28, 520, ["2 · Transcribe the whole VOD once",
                          "transcribe.py  ·  transcribe_chunked.py (very long)  ·  transcribe_diarized.py (speakers)",
                          "cached at transcript/words.json, reused by every branch"])
arrow([(TX, y), (TX, y + 26)])
dy = y + 28 + 50
dbot = diamond(TX, dy, 330, 100, ["3 · What are we making?", "pick any combination"])

# ---- four columns ------------------------------------------------------------
COLS = {"A": 165, "B": 445, "C": 725, "D": 1135}
CW = 250
top = dbot + 70
split_y = dbot + 30
out.append(f'<path d="M {TX},{dbot} L {TX},{split_y} M {COLS["A"]},{split_y} L {COLS["D"]},{split_y}" fill="none" stroke="#6b7385" stroke-width="2"/>')
for k, x in COLS.items():
    arrow([(x, split_y), (x, top - 2)])

hdr = {"A": "A · Full VOD cleanup", "B": "B · Highlight edit", "C": "C · VOD-style long-form", "D": "D · Shorts batch"}


def column(x, steps, dest):
    yy = top
    for i, (lines, kind, dashed) in enumerate(steps):
        yy = box(x, yy, CW, lines, kind, dashed=dashed)
        arrow([(x, yy), (x, yy + 24)])
        yy += 26
    return box(x, yy, CW, dest, "out")


column(COLS["A"], [
    (["A · Full VOD cleanup", "whole stream, not a reel"], "auto", False),
    (["Trim dead air", "transcript gaps → ~1s breathing room"], "auto", False),
    (["Censor", "cut scenes for slurs / racial", "topics · excise “fuck” frames"], "auto", False),
    (["Build Resolve timeline", "resolve_build_timeline.py", "(trimmable clips, never flattened)"], "auto", False),
    (["You finish + export", "in Resolve"], "manual", False),
], ["VOD/<date_GAME>/"])

column(COLS["B"], [
    (["B · Highlight edit", "20–40 min, length = ceiling"], "auto", False),
    (["Pick the moments", "OBS markers first (context from", "~60s before), else transcript scan"], "auto", False),
    (["Build Resolve timeline", "yellow markers = funny,", "cyan = set-pieces"], "auto", False),
    (["SRT + metadata", "build_srt_from_clip_infos.py"], "auto", False),
    (["You finish + export", "in Resolve"], "manual", False),
], ["EDITS/<date_GAME>/"])

column(COLS["C"], [
    (["C · VOD-style long-form", "chronological, ~50 min"], "auto", False),
    (["Write a plan", "kept ranges of one recording"], "auto", False),
    (["build_vod_cut.py", "tightens words, excises “fuck”"], "auto", False),
    (["One segment list → all of:", "SRT · metadata + chapters ·", "flagged words · clip_infos · MP4"], "auto", False),
    (["You review", "(optionally rebuild in Resolve)"], "manual", False),
], ["EDITS/<date_GAME>/"])

# ---- shorts column (with the transcription branch) ---------------------------
X = COLS["D"]
DW = 420
yy = box(X, top, DW, ["D · Shorts batch", "30–90s each, funniest self-contained moments"])
arrow([(X, yy), (X, yy + 24)]); yy += 26
yy = box(X, yy, DW, ["Pick moments", "OBS markers first · flagged words stay in (reported, not cut)"])
arrow([(X, yy), (X, yy + 24)]); yy += 26
yy = box(X, yy, DW, ["Build clip folders · prep_shorts_batch.py",
                     "<clip>.mp4 + captions.json/.srt (VOD transcript) + metadata",
                     "layout: split · full-bleed + facecam.exe · blur-stack"])
arrow([(X, yy), (X, yy + 24)]); yy += 26
yy = box(X, yy, DW, ["Optional: re-cut by hand in Resolve",
                     "build_group_timelines.py → you trim + export",
                     "a re-cut goes in a named variant subfolder"], "manual", dashed=True)
arrow([(X, yy), (X, yy + 22)])
qy = yy + 22 + 55
qb = diamond(X, qy, 360, 110, ["Transcribe the short pre-render?", "(the rendered clip itself)"])

LX, RX = X - 105, X + 105
BW = 195
by = qb + 50
edge = qy + 55 * (1 - 105 / 180)  # where x = X±105 meets the diamond's lower edges
arrow([(LX, edge), (LX, by - 2)], "YES", LX - 24, edge + 26)
arrow([(RX, edge), (RX, by - 2)], "NO", RX + 22, edge + 26)
ly = box(LX, by, BW, ["Re-transcribe the short",
                      "WhisperX + forced alignment",
                      "1 word / card, accurate times",
                      "verify_caption_timing.py",
                      "use when: re-cut, garbled,",
                      "or captions must be exact"])
ry = box(RX, by, BW, ["Skip it",
                      "keep the captions built",
                      "from the VOD transcript",
                      "(fine when the cut is",
                      "unchanged, words clean)"], h=ly - by)
skip_mid = (by + ry) / 2
my = ly + 40
arrow([(LX, ly), (LX, my), (X, my), (X, my + 22)])
out.append(f'<path d="M {RX},{ry} L {RX},{my} L {X},{my}" fill="none" stroke="#6b7385" stroke-width="2"/>')
teaser_top = my + 24
yy = box(X, teaser_top, DW, ["Add the teaser · add_teaser.py",
                             "2–5s of the short's funniest beat, played first",
                             "captions copied + shifted · originals → no-teaser/"])
teaser_mid = (teaser_top + yy) / 2
arrow([(X, yy), (X, yy + 24)]); yy += 26
yy = box(X, yy, DW, ["You edit captions in caption-editor",
                          "text · speakers (colors) · notes (fx words) · image/GIF links",
                          "your edits are final — rendered exactly as written"], "manual")
arrow([(X, yy), (X, yy + 24)]); yy += 26
yy = box(X, yy, DW, ["Render + composite  (only when you say go)",
                     "render_captions.py → ProRes 4444 overlay + note images",
                     "ffmpeg lays it over the clip → <clip>_captioned.mp4"])
arrow([(X, yy), (X, yy + 24)]); yy += 26
meta_top = yy
yy = box(X, yy, DW, ["metadata.txt", "YouTube Shorts · TikTok · Instagram Reels — same wording"])
# posting with no captions at all: after the teaser, straight to metadata
GX = X + DW / 2 + 40
meta_mid = (meta_top + yy) / 2
arrow([(X + DW / 2, teaser_mid), (GX, teaser_mid), (GX, meta_mid), (X + DW / 2 + 2, meta_mid)], dashed=True)
out.append(f'<text transform="translate({GX + 16},{(teaser_mid + meta_mid) / 2}) rotate(90)" text-anchor="middle" font-size="13" font-weight="700" fill="#8a4fd6">posting uncaptioned? skip to metadata</text>')
arrow([(X, yy), (X, yy + 24)]); yy += 26
yend = box(X, yy, DW, ["CLIPS/<date_GAME>/<clip>/"], "out")

# ---- legend ------------------------------------------------------------------
ly0 = H - 70
items = [("auto", "automated (Claude + scripts)", False), ("manual", "your hands-on step", False),
         ("manual", "optional", True), ("choice", "decision", False), ("out", "deliverable folder", False)]
x0 = 70
for kind, label, dashed in items:
    fill, stroke = C[kind]
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    rx = 13 if kind == "out" else 5
    out.append(f'<rect x="{x0}" y="{ly0}" width="34" height="26" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')
    out.append(f'<text x="{x0 + 44}" y="{ly0 + 18}" font-size="14" fill="#1d2330">{escape(label)}</text>')
    x0 += 60 + len(label) * 7.6

assert yend < ly0 - 20, (yend, ly0)
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">'
       '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
       '<path d="M0,0 L10,5 L0,10 z" fill="#6b7385"/></marker></defs>'
       f'<rect width="{W}" height="{H}" fill="#ffffff"/>' + "\n".join(out) + "</svg>")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow.svg"), "w", encoding="utf-8").write(svg)
print("ok, shorts column ends at", yend)
