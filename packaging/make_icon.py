"""Draws the Fasway app icon (same design as web/icon.svg) and saves .icns (macOS) + .ico (Windows)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "build"
S = 1024
k = S / 64  # icon.svg uses a 64x64 viewBox

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(14 * k), fill="#4f8cff")
# "F" path from icon.svg: M20 16h26v8H29v6h14v8H29v12h-9z
pts = [(20, 16), (46, 16), (46, 24), (29, 24), (29, 30), (43, 30), (43, 38), (29, 38), (29, 50), (20, 50)]
d.polygon([(x * k, y * k) for x, y in pts], fill="white")

OUT.mkdir(exist_ok=True)
img.save(OUT / "Fasway.icns")
img.save(OUT / "Fasway.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(OUT / "Fasway.png")
print("icons written to", OUT)
