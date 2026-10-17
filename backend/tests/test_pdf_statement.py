"""PDF bank-statement import: several real-world layouts, reconciliation, passwords, scans, and the API."""
from datetime import date, timedelta

import pytest
from fpdf import FPDF
from sqlalchemy import select

from app.models import SmeTransaction

from app.pdf_statement import StatementError, parse_money, read_statement
from tests.test_import import new_business, upload

TODAY = date.today()
BASE = date(2026, 3, 31)       # fixed statement dates keep day/month detection deterministic


def build_pdf(pages: list[list[tuple[float, str]]], *, header: list[tuple[float, str]] | None = None,
              preamble: list[str] = (), user_password: str | None = None, align_right: set[int] = frozenset(),
              dark_header: bool = False) -> bytes:
    """Draw a statement. Each page is a list of lines; each line a list of (x, text). Header repeats per page.

    Columns whose x is in `align_right` are drawn right-aligned at x (like real statements' money columns).
    dark_header draws the header as white text on a dark bar, as many banks do.
    """
    pdf = FPDF(unit="pt", format="A4")
    pdf.set_auto_page_break(False)
    if user_password:
        pdf.set_encryption(owner_password="owner-secret", user_password=user_password)
    pdf.set_font("Helvetica", size=9)
    for lines in pages:
        pdf.add_page()
        y = 50
        for text in preamble:
            pdf.text(40, y, text)
            y += 14
        y += 10
        for k, line in enumerate(([header] if header else []) + lines):
            is_bar = dark_header and header and k == 0
            if is_bar:
                pdf.set_fill_color(11, 79, 138)
                pdf.rect(34, y - 11, 540, 16, style="F")
                pdf.set_text_color(255, 255, 255)
            for x, text in line:
                if x in align_right:
                    pdf.text(x - pdf.get_string_width(text), y, text)
                else:
                    pdf.text(x, y, text)
            if is_bar:
                pdf.set_text_color(0, 0, 0)
            y += 14
        pdf.text(40, 800, "Page 1 of 2  -  Thank you for banking with us")
    return bytes(pdf.output())


def d(days_ago: int, fmt: str = "%d/%m/%Y") -> str:
    return (BASE - timedelta(days=days_ago)).strftime(fmt)


# Layout A: Date | Description | Withdrawals | Deposits | Balance  (two pages, wrapped text, opening/closing)
A_HEADER = [(40, "Date"), (110, "Description"), (330, "Withdrawals"), (420, "Deposits"), (510, "Balance")]
RIGHT_A = {380, 465, 560}


def layout_a() -> bytes:
    p1 = [
        [(110, "Opening balance"), (560, "10,000.00")],
        [(40, d(40)), (110, "Card sales settlement"), (465, "2,450.00"), (560, "12,450.00")],
        [(40, d(38)), (110, "Rent payment to Parkview"), (380, "5,200.00"), (560, "7,250.00")],
        [(110, "Properties Ltd - October")],                                   # wrapped description
        [(40, d(35)), (110, "Transfer 50.00 to savings"), (380, "50.00"), (560, "7,200.00")],
    ]
    p2 = [
        [(40, d(30)), (110, "Golden Mill Flour supplier"), (380, "1,180.40"), (560, "6,019.60")],
        [(40, d(28)), (110, "Card sales settlement"), (465, "3,105.75"), (560, "9,125.35")],
        [(110, "Closing balance"), (560, "9,125.35")],
    ]
    return build_pdf([p1, p2], header=A_HEADER, align_right=RIGHT_A,
                     preamble=["Example Bank PLC", "Account 1234 5678 9012", f"Statement period {d(41)} to {d(27)}"])


def test_layout_debit_credit_balance_columns():
    r = read_statement(layout_a())
    assert [row["amount"] for row in r.rows] == ["2450.00", "-5200.00", "-50.00", "-1180.40", "3105.75"]
    assert r.rows[1]["description"] == "Rent payment to Parkview Properties Ltd - October"
    assert r.rows[2]["description"] == "Transfer 50.00 to savings"     # number inside the text stays text
    assert r.rows[0]["date"] == (BASE - timedelta(days=40)).isoformat()
    assert r.info["openingBalance"] == 10000.0 and r.info["closingBalance"] == 9125.35
    assert r.info["mismatchedRows"] == 0 and r.info["reconciledRows"] == 5
    assert r.info["layout"] == "columns" and r.info["pages"] == 2
    assert not r.warnings and not r.issues


def test_reconciliation_flags_a_misread_row():
    pdf = build_pdf([[
        [(40, d(20)), (110, "Card sales"), (465, "100.00"), (560, "1,100.00")],
        [(40, d(19)), (110, "Supplier"), (380, "40.00"), (560, "1,000.00")],     # should be 1,060.00
        [(40, d(18)), (110, "Card sales"), (465, "10.00"), (560, "1,010.00")],
    ]], header=A_HEADER, align_right=RIGHT_A)
    r = read_statement(pdf)
    assert r.info["mismatchedRows"] == 1
    assert "don't add up" in r.warnings[0]


# Layout B: Txn Date | Value Date | Particulars | Amount | Balance  - unsigned amounts, newest first
def test_unsigned_amount_column_uses_balance_for_direction():
    fmt = "%d %b %Y"
    header = [(40, "Txn Date"), (105, "Value Date"), (170, "Particulars"), (420, "Amount"), (510, "Balance")]
    lines = [  # newest first, as many banks print
        [(40, d(10, fmt)), (105, d(10, fmt)), (170, "BKASH MERCHANT SETTLEMENT"), (460, "8,000.00"), (560, "51,500.00")],
        [(40, d(12, fmt)), (105, d(11, fmt)), (170, "ELECTRICITY DESCO BILL"), (460, "1,500.00"), (560, "43,500.00")],
        [(40, d(14, fmt)), (105, d(14, fmt)), (170, "POS SALES"), (460, "5,000.00"), (560, "45,000.00")],
        [(40, d(15, fmt)), (105, d(15, fmt)), (170, "Balance brought forward"), (560, "40,000.00")],
    ]
    r = read_statement(build_pdf([lines], header=header, align_right={460, 560}))
    by_desc = {row["description"]: row["amount"] for row in r.rows}
    assert by_desc == {"BKASH MERCHANT SETTLEMENT": "8000.00", "ELECTRICITY DESCO BILL": "-1500.00",
                       "POS SALES": "5000.00"}
    assert r.info["mismatchedRows"] == 0
    assert r.info["openingBalance"] == 40000.0


def test_unsigned_amounts_without_balance_are_reported_not_guessed():
    header = [(40, "Date"), (110, "Description"), (420, "Amount")]
    r = read_statement(build_pdf([[[(40, d(5)), (110, "Something"), (460, "25.00")],
                                   [(40, d(4)), (110, "Other thing"), (460, "5.00")]]],
                                 header=header, align_right={460}))
    assert r.rows == []
    assert len(r.issues) == 2 and "money in or out" in r.issues[0]["errors"][0]


# Layout C: no header row, "Mon DD" dates without a year, CR/DR suffixes, balance last
def test_no_header_text_dates_and_cr_dr():
    year_line = f"Statement for period ending {TODAY.year}"
    lines = [
        [(40, "Jan 03"), (110, "Square payout"), (400, "1,250.00 CR"), (500, "3,250.00 CR")],
        [(40, "Jan 05"), (110, "Insurance premium"), (400, "900.00 DR"), (500, "2,350.00 CR")],
    ]
    r = read_statement(build_pdf([lines], preamble=[year_line]))
    assert [row["amount"] for row in r.rows] == ["1250.00", "-900.00"]
    assert r.rows[0]["date"] == date(TODAY.year, 1, 3).isoformat()
    assert r.info["layout"] == "inferred"


# Layout D: US style - single signed Amount column, MM/DD/YYYY detected from a day > 12
def test_signed_amount_column_and_us_dates():
    header = [(40, "Posting Date"), (130, "Description"), (430, "Amount")]
    lines = [
        [(40, "01/20/2026"), (130, "STRIPE TRANSFER"), (470, "1,904.22")],
        [(40, "01/02/2026"), (130, "ADOBE SUBSCRIPTION"), (470, "-54.99")],
        [(130, "ADOBE.COM CA")],
    ]
    r = read_statement(build_pdf([lines], header=header, align_right={470}))
    assert r.rows[0] == {"date": "2026-01-20", "description": "STRIPE TRANSFER", "amount": "1904.22"}
    assert r.rows[1] == {"date": "2026-01-02", "description": "ADOBE SUBSCRIPTION ADOBE.COM CA", "amount": "-54.99"}


def test_ambiguous_numeric_dates_ask_for_the_format():
    header = [(40, "Date"), (110, "Description"), (330, "Debit"), (420, "Credit")]
    pdf = build_pdf([[[(40, "03/04/2026"), (110, "Sales"), (465, "10.00")]]], header=header, align_right={380, 465})
    with pytest.raises(StatementError, match="day/month"):
        read_statement(pdf)
    assert read_statement(pdf, date_order="dmy").rows[0]["date"] == "2026-04-03"
    assert read_statement(pdf, date_order="mdy").rows[0]["date"] == "2026-03-04"


def test_password_protected_pdf():
    pdf = build_pdf([[[(40, d(3)), (110, "Card sales"), (465, "10.00"), (560, "10.00")]]],
                    header=A_HEADER, align_right=RIGHT_A, user_password="0412")
    with pytest.raises(StatementError, match="password-protected"):
        read_statement(pdf)
    with pytest.raises(StatementError, match="not correct"):
        read_statement(pdf, password="wrong")
    assert read_statement(pdf, password="0412").rows[0]["amount"] == "10.00"


def test_scanned_pdf_is_explained():
    pdf = FPDF()
    pdf.add_page()
    pdf.rect(20, 20, 100, 100)            # no text layer, like a scan
    with pytest.raises(StatementError, match="scan"):
        read_statement(bytes(pdf.output()))


def test_garbage_is_rejected():
    with pytest.raises(StatementError, match="Could not read"):
        read_statement(b"%PDF-1.4 this is not really a pdf")


@pytest.mark.parametrize("text,value", [
    ("1,234.56", (1234.56, None)), ("(50.00)", (-50.0, None)), ("12.00-", (-12.0, None)),
    ("1.234,56", (1234.56, None)), ("Tk5,000.00", (5000.0, None)), ("12.00CR", (12.0, "cr")),
    ("2026", None), ("000123", None), ("12.5", None),
])
def test_parse_money(text, value):
    assert parse_money(text) == value


# ---- through the API ------------------------------------------------------------------------

def test_pdf_import_end_to_end(client):
    new_business(client)
    pdf = layout_a()
    preview = upload(client, "transactions", pdf, name="statement.pdf", dry_run=True)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dryRun"] and body["imported"] == 5 and body["rejected"] == 0
    assert body["statement"]["closingBalance"] == 9125.35 and body["warnings"] == []
    categories = {row["Description"]: row["Category"] for row in body["preview"]}
    assert categories["Rent payment to Parkview Properties Ltd - October"] == "Rent"
    assert categories["Transfer 50.00 to savings"] == "Transfer"

    done = upload(client, "transactions", pdf, name="statement.pdf").json()
    assert done["imported"] == 5
    again = upload(client, "transactions", pdf, name="statement.pdf").json()
    assert again["imported"] == 0 and again["duplicates"] == 5        # re-importing is safe


def test_pdf_import_needs_password_and_chosen_account(client):
    new_business(client)
    h = {"X-CSRF-Token": client.cookies.get("sme_csrf")}
    savings = client.post("/api/business/accounts", json={"name": "Reserve", "accountType": "savings",
                                                          "last4": "9999", "balance": 500}, headers=h).json()
    pdf = build_pdf([[[(40, d(3)), (110, "Interest"), (465, "1.25"), (560, "501.25")]]],
                    header=A_HEADER, align_right=RIGHT_A, user_password="pw")
    r = upload(client, "transactions", pdf, name="s.pdf", dry_run=True)
    assert r.status_code == 422 and "password" in r.json()["detail"]

    r = client.post("/api/import/transactions", files={"file": ("s.pdf", pdf)}, headers=h,
                    data={"dry_run": "false", "password": "pw", "account_id": str(savings["id"])})
    assert r.status_code == 200 and r.json()["imported"] == 1
    with client.session() as s:
        stored = s.scalar(select(SmeTransaction.AccountId).where(SmeTransaction.Description == "Interest"))
    assert stored == savings["id"]

    other = client.post("/api/import/transactions", files={"file": ("s.pdf", pdf)}, headers=h,
                        data={"dry_run": "true", "password": "pw", "account_id": "999999"})
    assert other.status_code == 422          # someone else's (or a made-up) account is refused


def test_pdf_rejected_for_invoices(client):
    new_business(client)
    r = upload(client, "invoices", layout_a(), name="invoices.pdf", dry_run=True)
    assert r.status_code == 422 and "bank statements" in r.json()["detail"]
