"""QR-код российского кассового чека (54-ФЗ).

На каждом чеке есть QR-код вида::

    t=20261007T1241&s=1250.00&fn=9999078900004312&i=12345&fp=2981614210&n=1

В нём точно записаны дата и время, сумма, номер фискального накопителя (ФН), номер
фискального документа (ФД), фискальный признак (ФП) и тип операции. Это надёжнее, чем
распознавать напечатанный текст: цифры в QR не «плывут» на мятом или выцветшем чеке.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl

OPERATIONS = {
    1: "приход",
    2: "возврат прихода",
    3: "расход",
    4: "возврат расхода",
}


class FiscalQRError(ValueError):
    """Строка не похожа на QR-код кассового чека или повреждена."""


@dataclass(frozen=True)
class FiscalReceipt:
    when: datetime
    total: Decimal
    fn: str  # номер фискального накопителя, 16 цифр
    fd: str  # номер фискального документа
    fp: str  # фискальный признак документа
    operation: int  # 1 приход, 2 возврат прихода, 3 расход, 4 возврат расхода

    @property
    def operation_name(self) -> str:
        return OPERATIONS.get(self.operation, f"операция {self.operation}")

    @property
    def is_refund(self) -> bool:
        return self.operation in (2, 4)

    @property
    def signed_total(self) -> Decimal:
        """Сумма со знаком: возврат уменьшает итог."""
        return -self.total if self.is_refund else self.total

    @property
    def key(self) -> tuple:
        """ФН + ФД + ФП однозначно определяют чек — по ним ищутся дубликаты."""
        return (self.fn, self.fd, self.fp)

    def to_qr(self) -> str:
        return (
            f"t={self.when:%Y%m%dT%H%M}&s={self.total:.2f}&fn={self.fn}"
            f"&i={self.fd}&fp={self.fp}&n={self.operation}"
        )


def _parse_time(value: str) -> datetime:
    # формат выбираем по длине: strptime допускает однозначные поля, и «20261003T1842»
    # по шаблону с секундами превратилось бы в 18:04:02
    fmt = {13: "%Y%m%dT%H%M", 15: "%Y%m%dT%H%M%S"}.get(len(value))
    try:
        if fmt and value[:8].isdigit() and value[9:].isdigit():
            return datetime.strptime(value, fmt)
    except ValueError:
        pass
    raise FiscalQRError(f"Не разобрал дату чека: {value!r}")


def parse_fiscal_qr(text: str) -> FiscalReceipt:
    """Разбирает строку из QR-кода чека. Порядок полей не важен, лишние поля игнорируются."""
    if not text or "fn=" not in text or "s=" not in text:
        raise FiscalQRError("Это не QR-код кассового чека")
    fields = dict(parse_qsl(text.strip(), keep_blank_values=True))
    missing = [k for k in ("t", "s", "fn", "i", "fp", "n") if not fields.get(k)]
    if missing:
        raise FiscalQRError(f"В QR-коде нет полей: {', '.join(missing)}")
    try:
        total = Decimal(fields["s"].replace(",", "."))
    except InvalidOperation:
        raise FiscalQRError(f"Неверная сумма: {fields['s']!r}") from None
    if total < 0 or total != total.quantize(Decimal("0.01")):
        raise FiscalQRError(f"Неверная сумма: {fields['s']!r}")
    fn, fd, fp = fields["fn"], fields["i"], fields["fp"]
    if not (fn.isdigit() and len(fn) == 16):
        raise FiscalQRError(f"Номер ФН должен состоять из 16 цифр: {fn!r}")
    if not (fd.isdigit() and fp.isdigit() and len(fp) <= 10):
        raise FiscalQRError("Номер документа и фискальный признак должны быть числами")
    try:
        operation = int(fields["n"])
    except ValueError:
        raise FiscalQRError(f"Неверный тип операции: {fields['n']!r}") from None
    if operation not in OPERATIONS:
        raise FiscalQRError(f"Неизвестный тип операции: {operation}")
    return FiscalReceipt(
        when=_parse_time(fields["t"]),
        total=total.quantize(Decimal("0.01")),
        fn=fn,
        fd=str(int(fd)),
        fp=str(int(fp)),
        operation=operation,
    )
