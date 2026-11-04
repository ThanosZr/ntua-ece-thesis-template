#!/usr/bin/env python3
"""The grey "figure goes here" image of the Word template. usage: placeholder.py out.png"""
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1800, 900
im = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(im)
grey = (150, 150, 150)
for x in range(0, W, 40):
    d.line([(x, 0), (min(x + 20, W - 1), 0)], fill=grey, width=6)
    d.line([(x, H - 1), (min(x + 20, W - 1), H - 1)], fill=grey, width=6)
for y in range(0, H, 40):
    d.line([(0, y), (0, min(y + 20, H - 1))], fill=grey, width=6)
    d.line([(W - 1, y), (W - 1, min(y + 20, H - 1))], fill=grey, width=6)
font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
f1, f2 = ImageFont.truetype(font, 64), ImageFont.truetype(font, 40)
def center(text, y, f, fill):
    d.text(((W - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)
center("Θέση σχήματος", 330, f1, (90, 90, 90))
center("Εισαγωγή → Εικόνες, ή επικόλληση (Ctrl+V)", 440, f2, (120, 120, 120))
center("Στοίχιση με το κείμενο · ≥ 300 dpi ή EMF/SVG", 510, f2, (120, 120, 120))
im.save(sys.argv[1], dpi=(300, 300))
