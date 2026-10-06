"""Российские кассовые чеки: разбор QR по 54-ФЗ, чтение с «фото», пачка → Excel, сверка с нейросетью."""

import io
import sys
from datetime import datetime
from decimal import Decimal

import pytest
import qrcode
from openpyxl import load_workbook
from PIL import Image

from receipt_ocr.parsers import ReceiptParser
from receipt_ocr.ru import FiscalQRError, parse_fiscal_qr, read_fiscal_qr
from receipt_ocr.ru.cli import main as cli_main
from receipt_ocr.ru.report import build_excel, monthly, process_receipts

sys.path.insert(
    0, str(__import__("pathlib").Path(__file__).parent)
)  # тесты здесь не пакет
from ru_samples import make_receipt, photograph, sample  # noqa: E402

QR = "t=20261007T1241&s=1250.00&fn=9999078900004312&i=12345&fp=2981614210&n=1"


# ---------- строка QR ----------


def test_parse_fiscal_qr():
    r = parse_fiscal_qr(QR)
    assert r.when == datetime(2026, 10, 7, 12, 41)
    assert r.total == Decimal("1250.00") and r.fn == "9999078900004312"
    assert (r.fd, r.fp, r.operation, r.operation_name) == (
        "12345",
        "2981614210",
        1,
        "приход",
    )


def test_minutes_are_not_split_into_seconds():
    """«T1842» — это 18:42, а не 18:04:02 (strptime допускает однозначные поля)."""
    assert parse_fiscal_qr(QR.replace("T1241", "T1842")).when == datetime(
        2026, 10, 7, 18, 42
    )


def test_time_with_seconds_and_any_field_order():
    r = parse_fiscal_qr(
        "n=2&fp=0012&i=007&fn=9999078900004312&s=99.9&t=20261007T124159"
    )
    assert r.when == datetime(2026, 10, 7, 12, 41, 59)
    assert (r.total, r.fd, r.fp) == (Decimal("99.90"), "7", "12")


def test_refund_has_negative_signed_total():
    r = parse_fiscal_qr(QR.replace("n=1", "n=2"))
    assert (
        r.is_refund
        and r.operation_name == "возврат прихода"
        and r.signed_total == Decimal("-1250.00")
    )


def test_roundtrip():
    r = parse_fiscal_qr(QR)
    assert parse_fiscal_qr(r.to_qr()) == r


@pytest.mark.parametrize(
    "text, hint",
    [
        ("https://shop.example/promo", "не QR-код кассового чека"),
        ("s=10.00&fn=9999078900004312&n=1", "нет полей"),
        (QR.replace("fn=9999078900004312", "fn=12345"), "16 цифр"),
        (QR.replace("s=1250.00", "s=12,5,0"), "Неверная сумма"),
        (QR.replace("s=1250.00", "s=12.505"), "Неверная сумма"),
        (QR.replace("n=1", "n=7"), "Неизвестный тип"),
        (QR.replace("T1241", "T2561"), "дату"),
    ],
)
def test_bad_qr_strings(text, hint):
    with pytest.raises(FiscalQRError, match=hint):
        parse_fiscal_qr(text)


# ---------- чтение с изображения ----------


def test_reads_flat_scan():
    r = sample()
    assert read_fiscal_qr(make_receipt(r)) == r


@pytest.mark.parametrize("seed", range(8))
def test_reads_phone_photos(seed):
    r = sample(fd=500 + seed)
    assert read_fiscal_qr(photograph(make_receipt(r), seed=seed)) == r


@pytest.mark.parametrize(
    "kw", [{"angle": 180}, {"angle": 25}, {"dark": 0.25}, {"blur": 2.6}]
)
def test_reads_hard_photos(kw):
    r = sample()
    assert read_fiscal_qr(photograph(make_receipt(r), seed=1, **kw)) == r


def test_small_tilted_photo_needs_upscaling():
    """Такой снимок zxing не читает «как есть» — помогает увеличение."""
    import zxingcpp

    img = photograph(make_receipt(sample()), seed=0, angle=40)
    small = img.resize((img.width // 3, img.height // 3))
    assert not zxingcpp.read_barcodes(
        small.convert("L"), formats=zxingcpp.BarcodeFormat.QRCode
    )
    assert read_fiscal_qr(small) == sample()


def test_no_qr_returns_none():
    assert read_fiscal_qr(Image.new("RGB", (600, 800), "white")) is None


def test_ad_qr_is_skipped_and_fiscal_found():
    receipt = make_receipt(sample())
    ad = qrcode.make("https://shop.example/promo", box_size=6).convert("L")
    canvas = Image.new(
        "L", (receipt.width + ad.width + 40, max(receipt.height, ad.height)), 255
    )
    canvas.paste(receipt, (0, 0))
    canvas.paste(ad, (receipt.width + 40, 0))
    assert read_fiscal_qr(canvas) == sample()
    assert read_fiscal_qr(ad) is None


def test_reads_from_bytes_and_path(tmp_path):
    buf = io.BytesIO()
    make_receipt(sample()).save(buf, format="PNG")
    assert read_fiscal_qr(buf.getvalue()) == sample()
    path = tmp_path / "check.png"
    path.write_bytes(buf.getvalue())
    assert read_fiscal_qr(str(path)) == sample()


# ---------- пачка чеков ----------


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "cheki"
    d.mkdir()
    jobs = {
        "01-pyaterochka.jpg": (
            sample(total="241.90", when="2026-09-28 18:42", fd=101),
            {},
        ),
        "02-apteka.jpg": (sample(total="1350.00", when="2026-10-02 10:05", fd=102), {}),
        "03-apteka-eshche-raz.jpg": (
            sample(total="1350.00", when="2026-10-02 10:05", fd=102),
            {"angle": -6},
        ),
        "04-vozvrat.jpg": (
            sample(n=2, total="350.00", when="2026-10-03 12:00", fd=103),
            {},
        ),
        "05-razmytyi.jpg": (
            sample(total="777.00", when="2026-10-04 09:00", fd=104),
            {"blur": 3.6},
        ),
    }
    for i, (name, (r, kw)) in enumerate(jobs.items()):
        photograph(make_receipt(r), seed=i, **kw).save(d / name, quality=88)
    (d / "spisok.txt").write_text("не картинка", encoding="utf-8")
    return d


def test_folder_statuses_and_totals(folder):
    entries = {e.file: e for e in process_receipts([folder])}
    assert len(entries) == 5  # txt пропущен
    assert entries["01-pyaterochka.jpg"].status == "ok"
    assert entries["03-apteka-eshche-raz.jpg"].status == "duplicate"
    assert "02-apteka.jpg" in entries["03-apteka-eshche-raz.jpg"].notes[0]
    assert entries["04-vozvrat.jpg"].amount == Decimal("-350.00")
    assert (
        entries["05-razmytyi.jpg"].status == "no_qr"
        and "--llm" in entries["05-razmytyi.jpg"].notes[0]
    )
    months = monthly(list(entries.values()))
    assert months[(2026, 9)] == {"buy": Decimal("241.90"), "refund": Decimal(0), "n": 1}
    assert months[(2026, 10)] == {
        "buy": Decimal("1350.00"),
        "refund": Decimal("350.00"),
        "n": 2,
    }


class FakeLLM:
    """Подменяет ReceiptProcessor: «нейросеть» отвечает заранее заданным."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def process_receipt(self, path, schema, model=None):
        name = path.replace("\\", "/").split("/")[-1]
        self.calls.append(name)
        answer = self.answers.get(name, {"error": "nothing"})
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_llm_fills_unreadable_and_checks_totals(folder):
    llm = FakeLLM(
        {
            "05-razmytyi.jpg": {
                "merchant_name": "Кофейня",
                "transaction_date": "2026-10-04",
                "transaction_time": "09:00",
                "total_amount": 777,
            },
            "02-apteka.jpg": {
                "merchant_name": "Аптека",
                "total_amount": 1530.0,
            },  # нейросеть ошиблась
            "01-pyaterochka.jpg": {"merchant_name": "Пятёрочка", "total_amount": 241.9},
            "04-vozvrat.jpg": RuntimeError("timeout"),
        }
    )
    entries = {e.file: e for e in process_receipts([folder], llm=llm)}
    blurry = entries["05-razmytyi.jpg"]
    assert (
        blurry.status == "llm_only"
        and blurry.amount == Decimal("777.00")
        and blurry.merchant == "Кофейня"
    )
    assert (
        entries["02-apteka.jpg"].status == "mismatch"
        and "1530.00" in entries["02-apteka.jpg"].notes[0]
    )
    assert (
        entries["01-pyaterochka.jpg"].status == "ok"
        and entries["01-pyaterochka.jpg"].merchant == "Пятёрочка"
    )
    assert (
        entries["04-vozvrat.jpg"].status == "ok"
    )  # сбой нейросети не мешает данным из QR
    assert len(llm.calls) == 5


def test_excel_report(folder):
    wb = load_workbook(io.BytesIO(build_excel(process_receipts([folder]))))
    rows = list(wb["Чеки"].values)
    assert rows[0][:3] == ("Дата и время", "Сумма, ₽", "Операция")
    by_file = {r[7]: r for r in rows[1:]}
    assert (
        by_file["04-vozvrat.jpg"][1] == -350.0
        and by_file["04-vozvrat.jpg"][2] == "возврат прихода"
    )
    assert by_file["03-apteka-eshche-raz.jpg"][8] == "дубликат — не учтён"
    summary = list(wb["По месяцам"].values)
    assert summary[1] == ("Сентябрь 2026", 241.9, 0.0, 241.9, 1)
    assert summary[2] == ("Октябрь 2026", 1350.0, 350.0, 1000.0, 2)
    assert summary[-1] == ("Всего", 1591.9, 350.0, 1241.9, 3)


def test_cli(folder, tmp_path, capsys):
    out = tmp_path / "report.xlsx"
    assert cli_main([str(folder), "-o", str(out)]) == 0
    assert out.exists() and "дубликат" in capsys.readouterr().out
    assert cli_main([str(tmp_path / "pusto")]) == 1


def test_broken_file_does_not_stop_batch(folder):
    (folder / "00-bityi.jpg").write_bytes(b"not an image")
    entries = {e.file: e for e in process_receipts([folder])}
    assert (
        entries["00-bityi.jpg"].status == "error"
        and entries["01-pyaterochka.jpg"].status == "ok"
    )


# ---------- исправленный разбор ответа нейросети ----------


@pytest.mark.parametrize(
    "response",
    [
        '```json\n{"total_amount": 10.0}```',  # закрывающие кавычки без переноса строки
        'Here is the JSON:\n```json\n{"total_amount": 10.0}\n```',  # пояснение перед блоком
        'Ответ: {"total_amount": 10.0}',
    ],
)
def test_parser_handles_real_world_llm_answers(response):
    assert ReceiptParser().parse(response) == {"total_amount": 10.0}
