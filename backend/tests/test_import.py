"""CSV/Excel import: parsing, validation, dedupe, invoice linking, and engines on a brand-new business."""
import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

from app.importer import ImportFileError, guess_category, parse_amount, parse_date, read_rows

STRONG = "correct horse battery staple"


def new_business(client) -> None:
    """Register a fresh, empty business (cookie session) and add one bank account."""
    r = client.post("/api/auth/register", json={
        "businessName": "Blue Fern Studio", "industry": "Professional Services", "region": "Dhaka",
        "foundedDate": "2022-03-01", "employees": 4, "currency": "USD", "fullName": "Nadia Rahman",
        "email": "nadia@bluefern.example", "password": STRONG, "acceptTerms": True})
    assert r.status_code == 201, r.text
    acct = client.post("/api/business/accounts", json={"name": "Main Account", "accountType": "checking",
                                                       "last4": "4821", "balance": 18000},
                       headers={"X-CSRF-Token": client.cookies.get("sme_csrf")})
    assert acct.status_code == 201, acct.text


def upload(client, kind, text_or_bytes, name="data.csv", dry_run=False, date_format="auto"):
    content = text_or_bytes.encode() if isinstance(text_or_bytes, str) else text_or_bytes
    return client.post(f"/api/import/{kind}", files={"file": (name, content)},
                       data={"dry_run": str(dry_run).lower(), "date_format": date_format},
                       headers={"X-CSRF-Token": client.cookies.get("sme_csrf")})


def history_csv(months: int = 8) -> str:
    """Weekly sales, monthly rent and payroll for `months` months, ending yesterday."""
    end = date.today() - timedelta(days=1)
    lines = ["Date,Description,Amount,Category"]
    d = end - timedelta(days=30 * months)
    while d <= end:
        lines.append(f"{d.isoformat()},Card sales,{2500 + (d.toordinal() % 7) * 40:.2f},")
        d += timedelta(days=7)
    for m in range(months):
        first = (end - timedelta(days=30 * m)).replace(day=1)
        lines.append(f"{first.isoformat()},Office rent,-1800.00,Rent")
        lines.append(f"{first.isoformat()},Payroll run,-4200.00,")  # category guessed from the text
    return "\n".join(lines) + "\n"


# ---- parsing --------------------------------------------------------------------------------

@pytest.mark.parametrize("text,value", [
    ("1,234.50", 1234.5), ("$-75.00", -75.0), ("(1,200.00)", -1200.0), ("1234,56", 1234.56), ("  300 ", 300.0),
])
def test_parse_amount(text, value):
    assert parse_amount(text) == value


def test_parse_amount_rejects_text():
    with pytest.raises(ValueError):
        parse_amount("twelve")


@pytest.mark.parametrize("text,fmt,expected", [
    ("2026-09-03", "auto", date(2026, 9, 3)), ("25/09/2026", "auto", date(2026, 9, 25)),
    ("09/25/2026", "auto", date(2026, 9, 25)), ("03/09/2026", "DD/MM/YYYY", date(2026, 9, 3)),
    ("03/09/2026", "MM/DD/YYYY", date(2026, 3, 9)), ("2026-09-03T10:00:00", "auto", date(2026, 9, 3)),
])
def test_parse_date(text, fmt, expected):
    assert parse_date(text, fmt) == expected


def test_ambiguous_date_needs_a_format():
    with pytest.raises(ValueError, match="ambiguous"):
        parse_date("03/09/2026")


@pytest.mark.parametrize("direction,text,category", [
    ("out", "ADP payroll 09/12", "Payroll"), ("out", "Google Workspace", "Software"),
    ("out", "Monthly office rent", "Rent"), ("out", "Stripe fees", "Bank & Card Fees"),
    ("in", "Interest earned", "Other Income"), ("in", "Card sales", "Sales"), ("out", "Transfer to savings", "Transfer"),
    ("in", "NPSB TRANSFER FROM ACME TRADING LTD", "Sales"), ("out", "BEFTN TRF TO GOLDEN MILL SUPPLIER", "Inventory"),
    ("out", "Internal fund transfer to reserve", "Transfer"),
    ("out", "Random shop", "Other Expense"),
])
def test_guess_category(direction, text, category):
    assert guess_category(direction, text) == category


def test_excel_and_header_aliases():
    wb = Workbook()
    ws = wb.active
    ws.append(["Posting Date", "Details", "Credit", "Debit"])
    ws.append([date(2026, 9, 1), "Card sales", 1200, None])
    ws.append([date(2026, 9, 2), "Rent", None, 900])
    buf = io.BytesIO()
    wb.save(buf)
    rows = read_rows(buf.getvalue(), "bank.xlsx")
    assert rows[0] == {"posting_date": "2026-09-01", "details": "Card sales", "credit": "1200", "debit": ""}


def test_unsupported_file_type():
    with pytest.raises(ImportFileError):
        read_rows(b"%PDF-1.7", "statement.pdf")


# ---- end-to-end through the API -----------------------------------------------------------------

def test_new_business_engines_handle_empty_ledger(client):
    new_business(client)
    dash = client.get("/api/dashboard/summary")
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["healthScore"]["score"] is None and "months" in body["healthScore"]["message"]
    assert body["forecast"]["summary"]["openingBalance"] == 18000
    assert client.get("/api/onboarding/status").json()["counts"]["accounts"] == 1


def test_transaction_import_preview_then_commit_and_dedupe(client):
    new_business(client)
    csv_text = history_csv(8) + "not-a-date,Broken row,10,\n2026-09-05,Zero row,0,\n"
    preview = upload(client, "transactions", csv_text, dry_run=True).json()
    assert preview["dryRun"] and preview["rejected"] == 2 and preview["imported"] > 30
    assert len(preview["errors"]) == 2 and preview["preview"]
    assert client.get("/api/onboarding/status").json()["counts"]["transactions"] == 0  # nothing written

    first = upload(client, "transactions", csv_text).json()
    assert first["imported"] == preview["imported"] and first["batchId"]
    again = upload(client, "transactions", csv_text).json()
    assert again["imported"] == 0 and again["duplicates"] == first["imported"]  # safe to re-import

    status = client.get("/api/onboarding/status").json()
    assert status["counts"]["transactions"] == first["imported"] and status["monthsOfHistory"] >= 7
    dash = client.get("/api/dashboard/summary").json()
    assert dash["healthScore"]["score"] is not None  # enough history now
    cats = {t["category"] for t in client.get("/api/ledger/transactions?limit=500").json()["items"]}
    assert {"Sales", "Rent", "Payroll"} <= cats  # categories given or guessed
    history = client.get("/api/import/history").json()
    assert len(history) == 2 and history[-1]["rejected"] == 2


def test_invoice_import_updates_and_payment_linking(client):
    new_business(client)
    today = date.today()
    inv = (f"invoice_no,customer,issue_date,due_date,amount\n"
           f"INV-9001,Acme Offices,{(today - timedelta(days=20)).isoformat()},{(today + timedelta(days=10)).isoformat()},3200\n"
           f"INV-9002,Harbor Tech,{(today - timedelta(days=50)).isoformat()},{(today - timedelta(days=20)).isoformat()},1500\n")
    r = upload(client, "invoices", inv).json()
    assert r["imported"] == 2
    pay = f"date,description,amount\n{(today - timedelta(days=2)).isoformat()},Payment ref INV-9002 thanks,1500.00\n"
    t = upload(client, "transactions", pay).json()
    assert t["linkedPayments"] == 1
    invoices = {i["invoiceNo"]: i for i in client.get("/api/ledger/invoices?status=all").json()}
    assert invoices["INV-9002"]["status"] == "paid" and invoices["INV-9001"]["status"] == "open"
    # Re-importing with a changed status updates instead of duplicating.
    paid = inv.replace("amount\n", "amount,status,paid_date\n").replace(",3200\n", f",3200,paid,{today.isoformat()}\n") \
        .replace(",1500\n", f",1500,paid,{(today - timedelta(days=2)).isoformat()}\n")
    r2 = upload(client, "invoices", paid).json()
    assert r2["updated"] == 1 and r2["duplicates"] == 1 and r2["imported"] == 0


def test_bill_import_and_validation(client):
    new_business(client)
    today = date.today()
    bills = (f"vendor,category,due_date,amount,recurring\n"
             f"City Power,Utilities,{(today + timedelta(days=12)).isoformat()},420,yes\n"
             f"Paper Co,,{(today + timedelta(days=5)).isoformat()},-30,\n"
             f",Rent,{today.isoformat()},100,\n")
    r = upload(client, "bills", bills).json()
    assert r["imported"] == 1 and r["rejected"] == 2
    assert {tuple(e["errors"]) for e in r["errors"]} == {("amount must be positive",), ("vendor is empty",)}
    unpaid = client.get("/api/ledger/bills").json()
    assert unpaid[0]["vendor"] == "City Power" and unpaid[0]["recurring"] is True


def test_import_permissions_and_limits(client):
    h = client.as_role("viewer")
    r = client.post("/api/import/transactions", files={"file": ("a.csv", b"date,description,amount\n")}, headers=h)
    assert r.status_code == 403
    new_business(client)
    missing = upload(client, "transactions", "when,what\n2026-01-01,x\n")
    assert missing.status_code == 422 and "Missing required column" in missing.json()["detail"]
    assert upload(client, "invoices", b"\x00\x01\x02", name="evil.exe").status_code == 422
    tpl = client.get("/api/import/templates/transactions.csv")
    assert tpl.status_code == 200 and tpl.text.startswith("date,description,amount")


def test_business_isolation_for_imports(client):
    """A new business's import never touches the demo business, and vice versa."""
    new_business(client)
    upload(client, "transactions", history_csv(2))
    client.cookies.clear()
    owner = client.as_role("owner")  # the demo bakery
    names = {t["counterparty"] for t in client.get("/api/ledger/transactions?limit=500", headers=owner).json()["items"]}
    assert "Card sales" not in names


def test_savings_only_business_still_has_operating_cash(client):
    """A business whose only account is a savings account runs on it: the dashboard must not show 0."""
    r = client.post("/api/auth/register", json={
        "businessName": "Savings Only Foods", "industry": "Food & Beverage", "region": "", "foundedDate": "2021-01-01",
        "employees": 3, "currency": "BDT", "fullName": "Karim Uddin", "email": "karim@savingsonly.example",
        "password": STRONG, "acceptTerms": True})
    assert r.status_code == 201, r.text
    h = {"X-CSRF-Token": client.cookies.get("sme_csrf")}
    client.post("/api/business/accounts", json={"name": "Operating account", "accountType": "savings",
                                                "last4": "7897", "balance": 250000}, headers=h)
    upload(client, "transactions", history_csv())
    summary = client.get("/api/dashboard/summary").json()
    assert summary["kpis"]["operatingCash"] == 250000
    assert summary["forecast"]["summary"]["openingBalance"] == 250000
