"""Draws the Fasway icon (same design as web/icon.svg: blue rounded square, white "F") for Android.

Writes:
  android/app/src/main/res/mipmap-*/ic_launcher.png             classic icon (Android 7)
  android/app/src/main/res/mipmap-*/ic_launcher_foreground.png  adaptive icon foreground (Android 8+)
  android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml     adaptive icon (+ monochrome, Android 13 themes)
  android/app/src/main/res/values/ic_launcher_background.xml     adaptive icon background colour
  assets/icon.png                                                 in-app logo (startup screen)
Run from the app folder:  python tool/make_icons.py   (needs Pillow)
"""
from pathlib import Path

from PIL import Image, ImageDraw

APP = Path(__file__).resolve().parent.parent
RES = APP / "android" / "app" / "src" / "main" / "res"
BLUE = "#4F8CFF"
# "F" path from web/icon.svg (64x64 viewBox): M20 16h26v8H29v6h14v8H29v12h-9z
F = [(20, 16), (46, 16), (46, 24), (29, 24), (29, 30), (43, 30), (43, 38), (29, 38), (29, 50), (20, 50)]
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
SS = 4  # draw 4x larger, then downscale: smooth edges


def classic(px: int) -> Image.Image:
    s = px * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = s / 64
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(14 * k), fill=BLUE)
    d.polygon([(x * k, y * k) for x, y in F], fill="white")
    return img.resize((px, px), Image.LANCZOS)


def foreground(px: int) -> Image.Image:
    """108dp canvas; the F (34 units tall) is drawn ~44dp tall, centred inside the 66dp safe zone."""
    s = px * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = (s * 44 / 108) / 34          # icon units -> pixels
    cx, cy = 33, 33                  # centre of the F's bounding box in icon units
    d.polygon([(s / 2 + (x - cx) * k, s / 2 + (y - cy) * k) for x, y in F], fill="white")
    return img.resize((px, px), Image.LANCZOS)


def main():
    for name, m in DENSITIES.items():
        folder = RES / f"mipmap-{name}"
        folder.mkdir(parents=True, exist_ok=True)
        classic(round(48 * m)).save(folder / "ic_launcher.png")
        foreground(round(108 * m)).save(folder / "ic_launcher_foreground.png")
    anydpi = RES / "mipmap-anydpi-v26"
    anydpi.mkdir(exist_ok=True)
    (anydpi / "ic_launcher.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/ic_launcher_background"/>\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
        '    <monochrome android:drawable="@mipmap/ic_launcher_foreground"/>\n'
        '</adaptive-icon>\n')
    (RES / "values").mkdir(exist_ok=True)
    (RES / "values" / "ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">{BLUE}</color>\n</resources>\n')
    (APP / "assets").mkdir(exist_ok=True)
    classic(512).save(APP / "assets" / "icon.png")
    print("icons written")


if __name__ == "__main__":
    main()
