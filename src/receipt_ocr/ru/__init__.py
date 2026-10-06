"""Российские кассовые чеки: QR-код по 54-ФЗ, выгрузка в Excel, сверка с нейросетью."""

from receipt_ocr.ru.fiscal import FiscalQRError, FiscalReceipt, parse_fiscal_qr
from receipt_ocr.ru.qr import find_qr_texts, read_fiscal_qr

__all__ = [
    "FiscalQRError",
    "FiscalReceipt",
    "find_qr_texts",
    "parse_fiscal_qr",
    "read_fiscal_qr",
]
