"""Синтетические фото российских чеков для тестов и демо.

Настоящие чеки в репозиторий класть нельзя: в них покупки и данные магазинов. Поэтому чек
рисуется программно (с правильным QR по 54-ФЗ), а потом «фотографируется»: поворот,
перспектива, размытие, шум, неравномерный свет, фон стола. Номера ФН начинаются с 9999 —
таких накопителей не существует.
"""

import random
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from receipt_ocr.ru.fiscal import FiscalReceipt

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]


def _font(size: int):
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def make_receipt(
    receipt: FiscalReceipt,
    shop: str = "ООО «Продукты у дома»",
    items=(("Хлеб бородинский", 1, "62.90"), ("Молоко 3,2% 1 л", 2, "89.50")),
) -> Image.Image:
    """Ровный «отсканированный» чек с QR-кодом."""
    w = 560
    f, fb = _font(22), _font(26)
    lines = [
        (shop, fb),
        ("ИНН 7709999995", f),
        ("г. Москва, ул. Лесная, д. 5", f),
        ("", f),
        ("КАССОВЫЙ ЧЕК", fb),
        (receipt.operation_name.upper(), fb),
        ("", f),
    ]
    for name, qty, price in items:
        lines += [(name, f), (f"   {qty} x {price} = {Decimal(price) * qty:.2f}", f)]
    lines += [
        ("", f),
        (f"ИТОГ            ={receipt.total:.2f}", fb),
        ("НДС не облагается", f),
        ("", f),
        (f"{receipt.when:%d.%m.%Y %H:%M}", f),
        (f"ФН {receipt.fn}", f),
        (f"ФД {receipt.fd}   ФП {receipt.fp}", f),
    ]
    qr = qrcode.make(receipt.to_qr(), box_size=6, border=2).convert("L")
    h = 40 + len(lines) * 32 + qr.height + 50
    img = Image.new("L", (w, h), 250)
    d = ImageDraw.Draw(img)
    y = 30
    for text, font in lines:
        d.text((34, y), text, font=font, fill=20)
        y += 32
    img.paste(qr, ((w - qr.width) // 2, y + 10))
    return img


def photograph(
    img: Image.Image,
    seed: int = 0,
    angle: float = None,
    blur: float = None,
    dark: float = None,
) -> Image.Image:
    """Делает из ровного чека «фото с телефона»."""
    rnd = random.Random(seed)
    angle = rnd.uniform(-9, 9) if angle is None else angle
    blur = rnd.uniform(0.4, 1.4) if blur is None else blur
    dark = rnd.uniform(0.55, 0.85) if dark is None else dark
    paper = img.convert("RGB").rotate(
        angle, expand=True, fillcolor=(70, 52, 40), resample=Image.Resampling.BICUBIC
    )
    # стол и тень
    bg = Image.new("RGB", (paper.width + 260, paper.height + 260), (92, 66, 48))
    bg.paste(paper, (130 + rnd.randint(-40, 40), 130 + rnd.randint(-40, 40)))
    # перспектива: телефон держали не ровно над чеком
    w, h = bg.size
    dx, dy = int(w * 0.06), int(h * 0.04)
    quad = (
        rnd.randint(0, dx),
        rnd.randint(0, dy),
        rnd.randint(0, dx),
        h - rnd.randint(0, dy),
        w - rnd.randint(0, dx),
        h - rnd.randint(0, dy),
        w - rnd.randint(0, dx),
        rnd.randint(0, dy),
    )
    bg = bg.transform(
        (w, h), Image.Transform.QUAD, quad, resample=Image.Resampling.BICUBIC
    )
    # свет: один край темнее
    shade = (
        Image.linear_gradient("L").rotate(rnd.choice([0, 90, 180, 270])).resize(bg.size)
    )
    shade = shade.point(lambda p: int(255 * (dark + (1 - dark) * p / 255)))
    bg = Image.composite(bg, Image.new("RGB", bg.size, (0, 0, 0)), shade)
    bg = bg.filter(ImageFilter.GaussianBlur(blur))
    noise = Image.effect_noise(bg.size, 12).convert("RGB")
    bg = Image.blend(bg, noise, 0.06)
    return bg.resize((int(w * 0.8), int(h * 0.8)), Image.Resampling.LANCZOS)


def sample(
    n: int = 1,
    total: str = "241.90",
    when: str = "2026-10-03 18:42",
    fd: int = 41237,
    fp: int = 2981614210,
    fn: str = "9999078900004312",
) -> FiscalReceipt:
    return FiscalReceipt(
        when=datetime.strptime(when, "%Y-%m-%d %H:%M"),
        total=Decimal(total),
        fn=fn,
        fd=str(fd),
        fp=str(fp),
        operation=n,
    )
