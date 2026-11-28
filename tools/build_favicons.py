"""Generează favicon.ico și PNG-urile de iconiță din același desen ca static/images/favicon.svg.

Google cere în rezultate o iconiță de cel puțin 48x48 (multiplu de 48); browserele vechi cer /favicon.ico.
Rulare: python tools/build_favicons.py  (are nevoie de Pillow și de fontul DejaVu Serif Bold)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "static" / "images"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
TOP, BOTTOM, GOLD = (0x1a, 0x1a, 0x2e), (0x16, 0x21, 0x3e), (0xC9, 0xA8, 0x4C)


def draw(size, radius=True):
    s = 4  # desenăm mare și micșorăm, pentru margini netede
    n = size * s
    grad = Image.new("RGB", (n, n))
    px = grad.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * n - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=n * 16 // 120 if radius else 0, fill=255)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, int(n * 0.5))
    d.text((n / 2, n * 0.47), "KP", font=font, fill="white", anchor="mm")
    w = max(1, round(n * 2.5 / 120))
    d.line([(n * 22 / 120, n * 94 / 120), (n * 98 / 120, n * 94 / 120)], fill=GOLD, width=w)
    return img.resize((size, size), Image.LANCZOS)


def main():
    draw(48).save(OUT / "favicon-48.png")
    draw(192).save(OUT / "favicon-192.png")
    draw(180, radius=False).save(OUT / "apple-touch-icon.png")  # iOS rotunjește singur colțurile
    draw(48).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("ok:", ", ".join(p.name for p in sorted(OUT.glob("*icon*"))))


if __name__ == "__main__":
    main()
