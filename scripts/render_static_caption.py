"""Render a single static caption line as a transparent overlay video (horizontal 1920x1080).

Usage: render_static_caption.py <text> <duration_s> <out.mov>
"""
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FPS = 30
FONT_PATH = r"C:\Users\Bem\Desktop\video-editor\assets\fonts\BebasNeue-Regular.ttf"
FONT_SIZE = 90
STROKE_WIDTH = 6
Y_FROM_BOTTOM = 160


def main():
    text, duration_s, out_path = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(frame)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=STROKE_WIDTH)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (W - tw) // 2 - bbox[0]
    y = H - Y_FROM_BOTTOM - th - bbox[1]
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255),
            stroke_width=STROKE_WIDTH, stroke_fill=(0, 0, 0, 255))

    total_frames = int(round(duration_s * FPS))
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
        "-alpha_bits", "8", out_path, "-loglevel", "warning",
    ], stdin=subprocess.PIPE)

    frame_bytes = frame.tobytes()
    for _ in range(total_frames):
        ff.stdin.write(frame_bytes)
    ff.stdin.close()
    ff.wait()
    print("wrote", out_path)


if __name__ == "__main__":
    main()
