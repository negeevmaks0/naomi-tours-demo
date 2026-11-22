"""Картинки для профиля Telegram-бота Naomi Tours (загружаются вручную через @BotFather).

    python design/make_bot_images.py

Создаёт в design/bot/:
  avatar-orange.png, avatar-navy.png — аватарка 640×640 (Edit Botpic), два варианта;
  description.jpg                    — картинка 640×360 для экрана до «Start» (Edit Description Picture).
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "design" / "bot"
FONTS = Path("C:/Windows/Fonts")
NAVY, NAVY_2 = (15, 42, 68), (26, 61, 95)
ACCENT, GOLD = (226, 112, 58), (201, 154, 62)
SS = 4  # суперсэмплинг для сглаживания


def gradient(size: int, c1, c2) -> Image.Image:
    """Диагональный градиент как у значка на сайте (135°)."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))
    return img


def draw_compass(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, ring, needle, hub,
                 tail=None) -> None:
    """Компас из логотипа сайта: кольцо и ромбовидная стрелка, повёрнутая на 45°."""
    width = r * 0.13
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ring, width=round(width))
    tip, side = r * 0.62, r * 0.2
    a = math.radians(-45)  # стрелка указывает вправо-вверх
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -uy, ux
    north = (cx + ux * tip, cy + uy * tip)
    south = (cx - ux * tip, cy - uy * tip)
    left = (cx + vx * side, cy + vy * side)
    right = (cx - vx * side, cy - vy * side)
    draw.polygon([north, left, right], fill=needle)
    draw.polygon([south, left, right], fill=tail or ring)
    hr = r * 0.07
    draw.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=hub)


def avatar(bg_from, bg_to, ring, needle, hub, name: str, tail=None) -> None:
    size = 640 * SS
    img = gradient(size, bg_from, bg_to)
    draw_compass(ImageDraw.Draw(img), size / 2, size / 2, size * 0.3, ring, needle, hub, tail)
    img.resize((640, 640), Image.LANCZOS).save(OUT / name)


def description_picture() -> None:
    w, h = 640, 360
    photo = Image.open(ROOT / "app/static/images/hero/mainz-bridge.jpg").convert("RGB")
    scale = max(w / photo.width, h / photo.height)
    photo = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.LANCZOS)
    left = (photo.width - w) // 2
    top = round((photo.height - h) * 0.4)
    img = photo.crop((left, top, left + w, top + h))

    # Затемнение слева направо, как в первом экране сайта.
    shade = Image.new("L", (w, h))
    sp = shade.load()
    for x in range(w):
        a = round(235 - 150 * (x / w))
        for y in range(h):
            sp[x, y] = a
    img = Image.composite(Image.new("RGB", (w, h), (10, 30, 50)), img, shade)

    d = ImageDraw.Draw(img)
    mark = 64
    logo = gradient(mark * SS, ACCENT, GOLD)
    draw_compass(ImageDraw.Draw(logo), mark * SS / 2, mark * SS / 2, mark * SS * 0.3,
                 (255, 255, 255), (255, 255, 255), ACCENT)
    logo = logo.resize((mark, mark), Image.LANCZOS)
    mask = Image.new("L", (mark, mark), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, mark - 1, mark - 1], radius=18, fill=255)
    img.paste(logo, (40, 44), mask)

    title = ImageFont.truetype(str(FONTS / "palab.ttf"), 52)
    title_light = ImageFont.truetype(str(FONTS / "pala.ttf"), 52)
    body = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 24)
    label = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 17)
    d.text((122, 48), "Naomi", font=title_light, fill="white")
    d.text((122 + d.textlength("Naomi", font=title_light), 48), "Tours", font=title, fill="white")
    d.text((40, 170), "Групповые поездки", font=body, fill=(230, 237, 243))
    d.text((40, 202), "из Франкфурта и Майнца", font=body, fill=(230, 237, 243))
    d.text((40, 290), "ИСПАНИЯ · ГРУЗИЯ · ФРАНЦИЯ", font=label, fill=(255, 194, 158))
    img.filter(ImageFilter.SHARPEN).save(OUT / "description.jpg", quality=90)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    avatar(ACCENT, GOLD, (255, 255, 255), NAVY, (255, 255, 255), "avatar-orange.png")
    avatar(NAVY, NAVY_2, (255, 255, 255), ACCENT, NAVY, "avatar-navy.png")
    description_picture()
    print("Готово:", ", ".join(p.name for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
