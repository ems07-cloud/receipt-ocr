"""receipt-ocr-ru: папка с фото российских чеков → Excel.

receipt-ocr-ru photos/ -o cheki.xlsx           # только QR-коды: бесплатно и без интернета
receipt-ocr-ru photos/ -o cheki.xlsx --llm     # + нейросеть для нечитаемых QR и сверки сумм
"""

import argparse
import os
import sys
from pathlib import Path

from receipt_ocr.ru.report import STATUS_RU, build_excel, monthly, process_receipts


def main(argv=None) -> int:
    # консоль Windows по умолчанию в cp1251: неизвестный символ не должен ронять программу
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(
        description="Российские кассовые чеки в Excel по QR-коду"
    )
    parser.add_argument("paths", nargs="+", help="фото чеков или папки с ними")
    parser.add_argument(
        "-o", "--output", default="cheki.xlsx", help="куда сохранить Excel"
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="подключить нейросеть (OPENAI_API_KEY) для чеков без QR и сверки сумм",
    )
    parser.add_argument("--model", default=None, help="модель для --llm")
    args = parser.parse_args(argv)

    llm = None
    if args.llm:
        from dotenv import load_dotenv

        from receipt_ocr.processors import ReceiptProcessor

        load_dotenv()
        llm = ReceiptProcessor()
        args.model = args.model or os.getenv("OPENAI_MODEL")

    entries = process_receipts(args.paths, llm=llm, model=args.model)
    if not entries:
        print("Не нашёл ни одного изображения", file=sys.stderr)
        return 1
    Path(args.output).write_bytes(build_excel(entries))

    for e in entries:
        mark = STATUS_RU[e.status] or "ok"
        amount = f"{e.amount:>10}" if e.amount is not None else " " * 10
        print(
            f"{e.file:<34} {amount}  {mark}{'  — ' + '; '.join(e.notes) if e.notes else ''}"
        )
    for (year, month), m in monthly(entries).items():
        print(
            f"{month:02d}.{year}: покупки {m['buy']:.2f}, возвраты {m['refund']:.2f}, чеков {m['n']}"
        )
    print(f"Сохранено: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
