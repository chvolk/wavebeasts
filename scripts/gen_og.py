#!/usr/bin/env python3
"""Generate the Open Graph / social preview card at play/static/og.png (1200x630). Build-time only;
Pillow is not a runtime dependency. Run: python scripts/gen_og.py"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = (10, 10, 11)
GOLD = (212, 175, 55)
GOLD_HI = (240, 207, 107)
SILVER = (199, 204, 214)
SILVER_HI = (238, 241, 246)
RED = (214, 69, 69)
BLACK = (10, 10, 11)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# subtle gold glow, top-right
glow = Image.new("RGB", (W, H), BG)
gd = ImageDraw.Draw(glow)
gd.ellipse([W - 620, -260, W + 260, 360], fill=(30, 25, 8))
img = Image.blend(img, glow, 0.6)
d = ImageDraw.Draw(img)

# gold hairline frame
d.rectangle([24, 24, W - 24, H - 24], outline=(58, 48, 20), width=2)


def font(sz, bold=True):
    for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),):
        try:
            return ImageFont.truetype(name, sz)
        except Exception:
            pass
    return ImageFont.load_default()


# wordmark + tagline (left)
d.text((70, 210), "WAVEBEASTS", font=font(96), fill=GOLD)
# fake letterspacing shadow line under it
d.line([74, 320, 74 + 700, 320], fill=(58, 48, 20), width=3)
d.text((74, 344), "Turn the real world into monsters.", font=font(38, False), fill=SILVER_HI)
d.text((74, 398), "Scan signals · catch · trade · battle", font=font(30, False), fill=SILVER)

# beast (right), gold on the glow
cx, cy = 960, 300
d.polygon([(cx - 90, cy - 70), (cx - 55, cy - 150), (cx - 15, cy - 78)], fill=GOLD)
d.polygon([(cx + 90, cy - 70), (cx + 55, cy - 150), (cx + 15, cy - 78)], fill=GOLD)
d.ellipse([cx - 120, cy - 60, cx + 120, cy + 150], fill=GOLD)
d.ellipse([cx - 78, cy - 10, cx + 78, cy + 130], fill=GOLD_HI)
d.ellipse([cx - 52, cy - 30, cx - 22, cy], fill=BLACK)
d.ellipse([cx + 22, cy - 30, cx + 52, cy], fill=BLACK)
d.ellipse([cx - 46, cy - 26, cx - 38, cy - 18], fill=SILVER_HI)
d.ellipse([cx + 30, cy - 26, cx + 38, cy - 18], fill=SILVER_HI)
d.polygon([(cx - 14, cy + 60), (cx, cy + 92), (cx + 14, cy + 60)], fill=RED)

out = os.path.join(os.path.dirname(__file__), "..", "play", "static", "og.png")
img.save(out, "PNG")
print("wrote", os.path.abspath(out), os.path.getsize(out), "bytes")
