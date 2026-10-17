"""OCR of scanned PDF statements. Tests that need the Tesseract binary skip when it is not installed
(it is in the Docker image and in CI)."""
import io
import random
from datetime import date, timedelta

import pytest
from PIL import Image, ImageFilter

from app import ocr
from app.pdf_statement import (
    StatementError, StatementLine, StatementResult, _fix_ocr_text, _ocr_policy, _reconcile, read_statement,
)
from tests.test_import import new_business, upload
from tests.test_pdf_statement import A_HEADER, BASE, RIGHT_A, build_pdf, d, layout_a

needs_tesseract = pytest.mark.skipif(not ocr.available(), reason="Tesseract OCR is not installed")


def scan(pdf_bytes: bytes, *, dpi: int = 200, tilt: float = 1.5, seed: int = 7) -> bytes:
    """Turn a text PDF into an image-only PDF that looks like an office scan."""
    import pypdfium2 as pdfium

    rnd = random.Random(seed)
    pages = []
    doc = pdfium.PdfDocument(pdf_bytes)
    for page in doc:
        img = page.render(scale=dpi / 72, grayscale=True).to_pil().convert("L")
        img = img.rotate(tilt, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        px = img.load()
        for _ in range(img.width * img.height // 400):           # dust and speckles
            px[rnd.randrange(img.width), rnd.randrange(img.height)] = rnd.choice((0, 90, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)                   # scanner compression
        pages.append(Image.open(io.BytesIO(buf.getvalue())).convert("L"))
    doc.close()
    out = io.BytesIO()
    pages[0].save(out, format="PDF", resolution=dpi, save_all=True, append_images=pages[1:])
    return out.getvalue()


def merge(*pdfs: bytes) -> bytes:
    import pypdfium2 as pdfium

    dst = pdfium.PdfDocument.new()
    for data in pdfs:
        dst.import_pages(pdfium.PdfDocument(data))
    buf = io.BytesIO()
    dst.save(buf)
    return buf.getvalue()


# ---- no Tesseract needed ---------------------------------------------------------------------

@pytest.mark.parametrize("raw,fixed", [
    ("1,2O4.5O", "1,204.50"), ("l5/O3/2026", "15/03/2026"), ("(3,1S0.00)", "(3,150.00)"),
    ("§0.00", "50.00"), ("9,125.35CR", "9,125.35CR"), ("BOLD", "BOLD"), ("Sales", "Sales"), ("O1", "O1"),
])
def test_ocr_digit_confusions(raw, fixed):
    assert _fix_ocr_text(raw) == fixed


def test_scan_without_ocr_explains(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    with pytest.raises(StatementError, match="OCR"):
        read_statement(scan(layout_a()))


def test_mixed_pdf_without_ocr_keeps_text_pages(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    text_page = build_pdf([[[(40, d(45)), (110, "Card sales"), (465, "100.00"), (560, "10,000.00")]]],
                          header=A_HEADER, align_right=RIGHT_A)
    r = read_statement(merge(text_page, scan(layout_a())))
    assert len(r.rows) == 1
    assert any("could not be read" in w for w in r.warnings)


def line(n, amount, balance, *, ocr_row=True, from_column=False, day=None):
    return StatementLine(page=1, line=n, day=day or date(2026, 3, n), description=f"row {n}", amount=amount,
                         balance=balance, ocr=ocr_row, from_column=from_column)


def test_misread_opening_balance_does_not_reject_a_good_row():
    rows = [line(1, 85000.0, 335000.0), line(2, -65000.0, 270000.0), line(3, 12450.5, 282450.5)]
    result = StatementResult(rows=[], labels=[])
    _reconcile(rows, 950000.0, result)          # OCR read 250,000 as 950,000
    assert [r.check for r in rows] == ["unchecked", "ok", "ok"]
    assert result.info["openingSuspect"] is True


def test_misread_balance_does_not_reject_two_good_rows():
    rows = [line(1, 100.0, 1100.0), line(2, -40.0, 1960.0), line(3, 10.0, 1070.0)]   # 1,060 read as 1,960
    _reconcile(rows, 1000.0, StatementResult(rows=[], labels=[]))
    assert [r.check for r in rows] == ["ok", "ok", "ok"]


def test_balance_overrides_a_sign_taken_from_column_position():
    rows = [line(1, 500.0, 500.0, from_column=True)]      # sat nearer "Deposit" but the balance fell
    _reconcile(rows, 1000.0, StatementResult(rows=[], labels=[]))
    assert rows[0].amount == -500.0 and rows[0].check == "ok"


def test_ocr_rows_that_contradict_the_balance_are_not_imported():
    rows = [line(1, 100.0, 1100.0), line(2, -45.0, 1060.0), line(3, 10.0, 1070.0)]   # 40 read as 45
    result = StatementResult(rows=[], labels=[])
    _reconcile(rows, 1000.0, result)
    trusted = _ocr_policy(rows, 1000.0, result)
    assert [trusted(r) for r in rows] == [True, False, True]


def test_mostly_unverifiable_scan_is_refused():
    rows = [line(n, 10.0 * n, 999.0 + n * 7) for n in range(1, 8)]   # balances never add up
    result = StatementResult(rows=[], labels=[])
    _reconcile(rows, 1000.0, result)
    with pytest.raises(StatementError, match="too unclear"):
        _ocr_policy(rows, 1000.0, result)


# ---- with Tesseract ---------------------------------------------------------------------------

@needs_tesseract
def test_scanned_statement_matches_the_digital_one():
    digital = read_statement(layout_a())
    scanned = read_statement(scan(layout_a()))
    assert scanned.info["ocrPages"] == [1, 2]
    assert [(r["date"], r["amount"]) for r in scanned.rows] == [(r["date"], r["amount"]) for r in digital.rows]
    assert scanned.info["mismatchedRows"] == 0
    assert scanned.info["openingBalance"] == 10000.0 and scanned.info["closingBalance"] == 9125.35
    assert "OCR" in scanned.warnings[0]                    # always asks the user to review


@needs_tesseract
def test_deskew_straightens_a_tilted_scan():
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(scan(layout_a(), tilt=2.5))[0]
    img = page.render(scale=1).to_pil().convert("L")
    _, angle = ocr.deskew(img)
    assert -3.0 <= angle <= -2.0


@needs_tesseract
def test_mixed_text_and_scanned_pages():
    text_page = build_pdf([[[(40, d(45)), (110, "Card sales"), (465, "100.00"), (560, "10,000.00")]]],
                          header=A_HEADER, align_right=RIGHT_A)
    r = read_statement(merge(text_page, scan(layout_a())))
    assert r.info["ocrPages"] == [2, 3]
    assert len(r.rows) == 6


def bank_statement(rows: int = 30) -> tuple[bytes, list[tuple[str, str]]]:
    """A longer statement with a white-on-dark header bar, value dates, references and a running balance."""
    header = [(40, "Txn Date"), (100, "Value Date"), (160, "Particulars"), (330, "Cheque/Ref"),
              (405, "Withdrawal (Dr)"), (480, "Deposit (Cr)"), (540, "Balance")]
    items = [("NPSB TRANSFER FROM ACME TRADING", "NP88213", 0, 85000.0), ("OFFICE RENT GULSHAN", "CHQ 004512", 65000.0, 0),
             ("BKASH MERCHANT SETTLEMENT", "BK77812", 0, 12450.5), ("SALARY DISBURSEMENT", "SAL0826", 68000.0, 0),
             ("DESCO ELECTRICITY BILL", "UT55123", 4380.25, 0), ("POS SALES SETTLEMENT", "POS9921", 0, 38900.0)]
    balance, lines, expected = 250000.0, [], []
    lines.append([(160, "BALANCE BROUGHT FORWARD"), (575, f"{balance:,.2f}")])
    for k in range(rows):
        desc, ref, dr, cr = items[k % len(items)]
        balance = round(balance - dr + cr, 2)
        day = d(80 - k * 2, "%d-%b-%Y")
        line = [(40, day), (100, day), (160, desc), (330, ref), (575, f"{balance:,.2f}")]
        line.append((460, f"{dr:,.2f}") if dr else (520, f"{cr:,.2f}"))
        lines.append(line)
        expected.append(((BASE - timedelta(days=80 - k * 2)).isoformat(), f"{(cr - dr):.2f}"))
    pages = [lines[:24], lines[24:]]
    return build_pdf(pages, header=header, dark_header=True, align_right={460, 520, 575},
                     preamble=["Eastern Commerce Bank PLC", "Statement of account"]), expected


@needs_tesseract
@pytest.mark.parametrize("dpi,tilt", [(300, 0.5), (200, 1.0)])
def test_realistic_scan_with_dark_header(dpi, tilt):
    """The OCR contract: nothing wrong is ever imported; what can't be confirmed is listed, and the total
    check accounts for exactly what was left out."""
    pdf, expected = bank_statement()
    r = read_statement(scan(pdf, dpi=dpi, tilt=tilt))
    got = [(row["date"], row["amount"]) for row in r.rows]
    assert all(g in expected for g in got)                       # no misread figure got through
    assert len(got) >= 0.9 * len(expected)
    missing = [e for e in expected if e not in got]
    assert len(r.issues) >= len(missing)                         # each one is reported to the user
    assert r.info["totalCheck"]["difference"] == pytest.approx(sum(float(a) for _, a in missing))


@needs_tesseract
def test_unreadable_scan_is_refused_not_guessed():
    pdf, _ = bank_statement()
    with pytest.raises(StatementError, match="too unclear|No transactions|no readable text"):
        read_statement(scan(pdf, dpi=110, tilt=2.0, seed=3))


@needs_tesseract
def test_scanned_pdf_through_the_api(client):
    new_business(client)
    body = upload(client, "transactions", scan(layout_a()), name="scan.pdf", dry_run=True).json()
    assert body["imported"] == 5 and body["statement"]["ocrPages"] == [1, 2]
    assert any("OCR" in w for w in body["warnings"])
