"""Поиск QR-кода чека на фотографии.

Фото с телефона бывают мелкими, тёмными или смазанными, поэтому если с первого раза код
не нашёлся, картинка обрабатывается по-разному: контраст, увеличение, резкость, порог яркости.
Работает локально через zxing-cpp — без нейросети и без интернета.
"""

from typing import Iterator, Optional, Union

from PIL import Image, ImageFilter, ImageOps

from receipt_ocr.ru.fiscal import FiscalQRError, FiscalReceipt, parse_fiscal_qr

ImageSource = Union[str, bytes, Image.Image]


def _open(image: ImageSource) -> Image.Image:
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, bytes):
        import io

        return Image.open(io.BytesIO(image))
    return Image.open(image)


def _variants(img: Image.Image) -> Iterator[Image.Image]:
    gray = ImageOps.exif_transpose(img).convert("L")
    yield gray
    yield ImageOps.autocontrast(gray, cutoff=2)
    if max(gray.size) < 1600:  # мелкий код — увеличиваем
        scale = 1600 / max(gray.size)
        big = gray.resize(
            (int(gray.width * scale), int(gray.height * scale)),
            Image.Resampling.LANCZOS,
        )
        yield ImageOps.autocontrast(big, cutoff=2)
    sharp = ImageOps.autocontrast(gray.filter(ImageFilter.SHARPEN), cutoff=2)
    yield sharp
    for threshold in (
        100,
        140,
        180,
    ):  # размытый или неровно освещённый код — разные пороги яркости
        yield sharp.point(lambda p, t=threshold: 255 if p > t else 0)
    # повороты не нужны: zxing сам находит код под любым углом и вверх ногами


def find_qr_texts(image: ImageSource) -> list[str]:
    """Все QR-коды, которые удалось прочитать на изображении (первая удачная попытка)."""
    import zxingcpp

    img = _open(image)
    for variant in _variants(img):
        found = [
            r.text
            for r in zxingcpp.read_barcodes(
                variant, formats=zxingcpp.BarcodeFormat.QRCode
            )
            if r.text
        ]
        if found:
            return found
    return []


def read_fiscal_qr(image: ImageSource) -> Optional[FiscalReceipt]:
    """Данные чека из QR-кода на фото или None, если кода чека на фото нет."""
    for text in find_qr_texts(image):
        try:
            return parse_fiscal_qr(text)
        except FiscalQRError:
            continue  # на фото может быть и другой QR, например реклама
    return None
