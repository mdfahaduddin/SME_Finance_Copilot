"""CSV / Excel / PDF-statement import of bank transactions, customer invoices and supplier bills.

Flow: parse the file -> normalise headers -> validate and convert each row -> (dry run: report only)
-> write valid rows, skip duplicates, link invoice payments, record an ImportBatch.

Design rules
  * Every row is validated independently; errors are reported per row (first 200) and never abort
    the whole file. The preview (dry run) shows exactly what a real import would do.
  * Re-importing the same file is safe: transactions and bills carry a dedupe key, invoices are
    unique per business by invoice number (a re-import updates status/paid date instead).
  * All values are treated as untrusted text: lengths are capped, numbers and dates strictly parsed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.engines.ledger import REVENUE_PREFIX

KINDS = ("transactions", "invoices", "bills")
MAX_ROWS = 20_000
MAX_ERRORS = 200
DATE_FORMATS = {"auto": None, "YYYY-MM-DD": "%Y-%m-%d", "DD/MM/YYYY": "%d/%m/%Y", "MM/DD/YYYY": "%m/%d/%Y"}

INCOME_CATEGORIES = ["Sales", "Other Income", "Transfer"]
EXPENSE_CATEGORIES = ["Inventory", "Payroll", "Rent", "Utilities", "Insurance", "Software", "Marketing",
                      "Maintenance", "Bank & Card Fees", "Professional Fees", "Taxes", "Loan Repayment",
                      "Owner Draw", "Equipment", "Other Expense", "Transfer"]

# Header aliases -> canonical field names.
ALIASES = {
    "date": ["date", "transaction_date", "txn_date", "posted", "posting_date", "booking_date", "value_date"],
    "amount": ["amount", "value", "net", "amount_usd"],
    "money_in": ["money_in", "credit", "credits", "deposit", "deposits", "paid_in", "inflow"],
    "money_out": ["money_out", "debit", "debits", "withdrawal", "withdrawals", "paid_out", "outflow"],
    "description": ["description", "details", "narrative", "memo", "reference", "particulars", "payee_details"],
    "counterparty": ["counterparty", "payee", "payer", "merchant", "name", "party"],
    "category": ["category", "type", "account_category"],
    "account": ["account", "account_name", "bank_account"],
    "invoice_no": ["invoice_no", "invoice_number", "invoice", "invoice_id", "number", "no"],
    "customer": ["customer", "client", "customer_name", "client_name", "bill_to"],
    "customer_email": ["customer_email", "email", "client_email"],
    "issue_date": ["issue_date", "invoice_date", "date_issued", "bill_date", "issued"],
    "due_date": ["due_date", "due", "payment_due"],
    "status": ["status", "state"],
    "paid_date": ["paid_date", "date_paid", "payment_date", "paid_on"],
    "vendor": ["vendor", "supplier", "vendor_name", "supplier_name", "payee"],
    "vendor_email": ["vendor_email", "supplier_email", "email"],
    "bill_no": ["bill_no", "bill_number", "reference", "vendor_reference", "invoice_no"],
    "recurring": ["recurring", "is_recurring", "repeats"],
    "memo": ["memo", "notes", "note", "description"],
}

REQUIRED = {
    "transactions": ["date", "description"],
    "invoices": ["invoice_no", "customer", "issue_date", "due_date", "amount"],
    "bills": ["vendor", "due_date", "amount"],
}

TEMPLATES = {
    "transactions": "date,description,amount,category,counterparty,account\n"
                    "2026-09-01,Card sales settlement,2450.00,Sales,Card processor,Operating Account\n"
                    "2026-09-01,Rent September,-5200.00,Rent,Parkview Properties,Operating Account\n",
    "invoices": "invoice_no,customer,customer_email,issue_date,due_date,amount,status,paid_date,memo\n"
                "INV-2001,Acme Offices,ap@acme.example,2026-09-03,2026-10-03,3200.00,open,,Catering\n"
                "INV-2002,Harbor Tech,finance@harbor.example,2026-08-15,2026-09-14,1850.00,paid,2026-09-20,\n",
    "bills": "vendor,bill_no,category,issue_date,due_date,amount,status,paid_date,recurring,vendor_email\n"
             "Golden Mill Flour Co.,GM-4411,Inventory,2026-09-29,2026-10-13,2400.00,open,,yes,accounts@goldenmill.example\n"
             "City Water Utility,,Utilities,2026-09-03,2026-09-20,380.00,paid,2026-09-19,yes,\n",
}

# Keyword rules for transactions without a category (first match wins).
CATEGORY_RULES: list[tuple[str, str, str]] = [  # (direction, regex, category)
    # Only moves between the business's own accounts. Bank statements name the payment rail on most
    # lines ("NPSB TRANSFER FROM <customer>", "BEFTN TRF"), and those are real income and spending.
    ("any", r"\b(to|from) (my |own )?savings\b|own account|between accounts|internal (fund )?transfer|"
            r"self transfer|transfer to self|sweep", "Transfer"),
    ("out", r"payroll|salar|wage|paye|gusto|adp\b", "Payroll"),
    ("out", r"\brent\b|lease|landlord", "Rent"),
    ("out", r"electric|power|\bgas\b|water|utilit|energy", "Utilities"),
    ("out", r"insur", "Insurance"),
    ("out", r"software|subscription|saas|google|microsoft|adobe|xero|quickbooks|zoom", "Software"),
    ("out", r"\bads?\b|advert|marketing|facebook|meta\b|instagram", "Marketing"),
    ("out", r"repair|maint|service call", "Maintenance"),
    ("out", r"\bfees?\b|charge|stripe|square|paypal|merchant", "Bank & Card Fees"),
    ("out", r"accountant|accounting|legal|lawyer|solicitor|consult", "Professional Fees"),
    ("out", r"\btax\b|irs|hmrc|\bvat\b|gst", "Taxes"),
    ("out", r"loan|repayment|mortgage|financ", "Loan Repayment"),
    ("out", r"owner|drawing|distribution|dividend", "Owner Draw"),
    ("out", r"supplier|wholesale|inventory|stock|ingredient|produce|packag", "Inventory"),
    ("in", r"interest|refund|rebate|grant", "Other Income"),
]

CATEGORY_LOOKUP = {c.lower(): c for c in INCOME_CATEGORIES + EXPENSE_CATEGORIES}
CATEGORY_LOOKUP.update({"salary": "Payroll", "salaries": "Payroll", "wages": "Payroll", "cogs": "Inventory",
                        "cost of goods sold": "Inventory", "supplies": "Inventory", "ingredients": "Inventory",
                        "revenue": "Sales", "income": "Sales", "fees": "Bank & Card Fees", "tax": "Taxes",
                        "loan": "Loan Repayment", "drawings": "Owner Draw", "other": "Other Expense"})


class ImportFileError(ValueError):
    """The whole file cannot be read (wrong type, no header, missing columns)."""


@dataclass
class RowResult:
    row: int
    values: dict | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    kind: str
    file_name: str
    dry_run: bool
    rows_total: int = 0
    imported: int = 0
    updated: int = 0
    duplicates: int = 0
    rejected: int = 0
    linked_payments: int = 0
    errors: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)
    batch_id: int | None = None
    warnings: list[str] = field(default_factory=list)
    statement: dict | None = None             # PDF statements: period, balances, reconciliation

    def to_dict(self) -> dict:
        return {"kind": self.kind, "fileName": self.file_name, "dryRun": self.dry_run, "rowsTotal": self.rows_total,
                "imported": self.imported, "updated": self.updated, "duplicates": self.duplicates,
                "rejected": self.rejected, "linkedPayments": self.linked_payments, "errors": self.errors,
                "columns": self.columns, "preview": self.preview, "batchId": self.batch_id,
                "warnings": self.warnings, "statement": self.statement}


# ---------------------------------------------------------------- reading files

def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")


def read_rows(content: bytes, file_name: str) -> list[dict[str, str]]:
    name = file_name.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as e:  # noqa: BLE001 - corrupt or non-Excel file
            raise ImportFileError("Could not read the Excel file. Save it as .xlsx or CSV and try again.") from e
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            raise ImportFileError("The sheet is empty.")
        keys = [_norm_header(str(h) if h is not None else "") for h in header]
        out = []
        for r in rows:
            if r is None or all(v is None or str(v).strip() == "" for v in r):
                continue
            out.append({k: _cell_text(v) for k, v in zip(keys, r) if k})
            if len(out) > MAX_ROWS:
                raise ImportFileError(f"Files are limited to {MAX_ROWS:,} rows.")
        return out
    if name.endswith((".csv", ".txt")):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        header = next(reader, None)
        if not header:
            raise ImportFileError("The file is empty.")
        keys = [_norm_header(h) for h in header]
        out = []
        for r in reader:
            if not any(c.strip() for c in r):
                continue
            out.append({k: v.strip() for k, v in zip(keys, r) if k})
            if len(out) > MAX_ROWS:
                raise ImportFileError(f"Files are limited to {MAX_ROWS:,} rows.")
        return out
    raise ImportFileError("Upload a .csv, .xlsx or .pdf file.")


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def map_columns(rows: list[dict[str, str]], kind: str) -> dict[str, str]:
    """canonical field -> source column present in the file."""
    present = set(rows[0].keys()) if rows else set()
    mapping = {}
    for canonical, aliases in ALIASES.items():
        for a in aliases:
            if a in present and a not in mapping.values():
                mapping[canonical] = a
                break
    missing = [f for f in REQUIRED[kind] if f not in mapping]
    if kind == "transactions" and "amount" not in mapping and not ({"money_in", "money_out"} & mapping.keys()):
        missing.append("amount (or money_in / money_out)")
    if missing:
        raise ImportFileError(f"Missing required column(s): {', '.join(missing)}. Download the template to see "
                              f"the expected headers.")
    return mapping


# ---------------------------------------------------------------- value parsing

def parse_amount(text: str) -> float | None:
    t = (text or "").strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")") or t.endswith("-")
    t = re.sub(r"[^\d.,\-]", "", t)
    if t.count(",") and t.count(".") == 0 and re.fullmatch(r"-?\d+,\d{1,2}", t):
        t = t.replace(",", ".")  # 1234,56 -> 1234.56
    t = t.replace(",", "")
    if t.endswith("-"):
        t = t[:-1]
    try:
        v = float(t)
    except ValueError:
        raise ValueError(f"'{text}' is not a valid amount")
    if abs(v) > 1e11:
        raise ValueError("amount is unrealistically large")
    return -abs(v) if neg else v


def parse_date(text: str, fmt: str = "auto") -> date:
    t = (text or "").strip()[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", (text or "").strip()) else (text or "").strip()
    if not t:
        raise ValueError("date is empty")
    if fmt != "auto":
        try:
            return datetime.strptime(t, DATE_FORMATS[fmt]).date()
        except ValueError:
            raise ValueError(f"'{text}' does not match {fmt}")
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", t)
    if not m:
        raise ValueError(f"'{text}' is not a recognised date (use YYYY-MM-DD)")
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if a > 12:
        return date(y, b, a)          # DD/MM/YYYY
    if b > 12:
        return date(y, a, b)          # MM/DD/YYYY
    if a == b:
        return date(y, a, b)
    raise ValueError(f"'{text}' is ambiguous (day/month) - choose a date format before importing")


def guess_category(direction: str, *texts: str) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for d, pattern, cat in CATEGORY_RULES:
        if d in ("any", direction) and re.search(pattern, blob):
            return cat
    return "Sales" if direction == "in" else "Other Expense"


def normalise_category(raw: str, direction: str, description: str, counterparty: str) -> str:
    c = CATEGORY_LOOKUP.get((raw or "").strip().lower())
    if c is None:
        return guess_category(direction, raw, description, counterparty)
    if direction == "in" and c not in INCOME_CATEGORIES:
        return "Other Income" if c not in ("Sales",) else c
    if direction == "out" and c == "Sales":
        return "Other Expense"
    return c


def _clip(v: str, n: int) -> str:
    return (v or "").strip()[:n]


def _sha(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------- row conversion

def convert_rows(kind: str, rows: list[dict[str, str]], mapping: dict[str, str], date_format: str,
                 accounts: dict[str, int], default_account: int | None) -> list[RowResult]:
    results = []
    seen: Counter = Counter()
    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        get = lambda f: raw.get(mapping[f], "") if f in mapping else ""  # noqa: E731
        res = RowResult(row=i)
        try:
            if kind == "transactions":
                res.values = _convert_txn(get, date_format, accounts, default_account, seen)
            elif kind == "invoices":
                res.values = _convert_invoice(get, date_format)
            else:
                res.values = _convert_bill(get, date_format, seen)
        except ValueError as e:
            res.errors.append(str(e))
        results.append(res)
    return results


def _convert_txn(get, fmt, accounts, default_account, seen) -> dict:
    d = parse_date(get("date"), fmt)
    if d > date.today() + timedelta(days=1):
        raise ValueError("date is in the future")
    amount = parse_amount(get("amount"))
    if amount is None:
        inflow, outflow = parse_amount(get("money_in")), parse_amount(get("money_out"))
        if inflow and outflow:
            raise ValueError("both money in and money out are filled")
        amount = abs(inflow) if inflow else (-abs(outflow) if outflow else None)
    if not amount:
        raise ValueError("amount is empty or zero")
    direction = "in" if amount > 0 else "out"
    description = _clip(get("description"), 500)
    counterparty = _clip(get("counterparty"), 200) or description[:60] or "-"
    account_name = get("account").strip().lower()
    account_id = accounts.get(account_name, default_account) if account_name else default_account
    if account_id is None:
        raise ValueError(f"unknown account '{get('account')}' - add it in Bank accounts first")
    category = normalise_category(get("category"), direction, description, counterparty)
    base = (account_id, d.isoformat(), f"{abs(amount):.2f}", direction, description.lower())
    seen[base] += 1  # identical rows in one file are distinct; re-importing the file is not
    return {"AccountId": account_id, "TxnDate": d, "Amount": round(abs(amount), 2), "Direction": direction,
            "Category": category, "Counterparty": counterparty, "Description": description,
            "DedupeKey": _sha(*base, seen[base])}


def _convert_invoice(get, fmt) -> dict:
    number = _clip(get("invoice_no"), 30)
    if not number:
        raise ValueError("invoice number is empty")
    customer = _clip(get("customer"), 200)
    if not customer:
        raise ValueError("customer is empty")
    issue, due = parse_date(get("issue_date"), fmt), parse_date(get("due_date"), fmt)
    if due < issue:
        raise ValueError("due date is before issue date")
    amount = parse_amount(get("amount"))
    if not amount or amount <= 0:
        raise ValueError("amount must be positive")
    paid = parse_date(get("paid_date"), fmt) if get("paid_date").strip() else None
    status = get("status").strip().lower() or ("paid" if paid else "open")
    if status not in ("open", "paid", "void"):
        raise ValueError("status must be open, paid or void")
    if status == "paid" and paid is None:
        raise ValueError("paid invoices need a paid date")
    email = _clip(get("customer_email"), 200)
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email):
        raise ValueError("customer email is not valid")
    return {"InvoiceNo": number, "Customer": customer, "CustomerEmail": email, "IssueDate": issue, "DueDate": due,
            "Amount": round(amount, 2), "Status": status, "PaidDate": paid if status == "paid" else None,
            "Memo": _clip(get("memo"), 500)}


def _convert_bill(get, fmt, seen) -> dict:
    vendor = _clip(get("vendor"), 200)
    if not vendor:
        raise ValueError("vendor is empty")
    due = parse_date(get("due_date"), fmt)
    issue = parse_date(get("issue_date"), fmt) if get("issue_date").strip() else due - timedelta(days=30)
    amount = parse_amount(get("amount"))
    if not amount or amount <= 0:
        raise ValueError("amount must be positive")
    paid = parse_date(get("paid_date"), fmt) if get("paid_date").strip() else None
    status = get("status").strip().lower() or ("paid" if paid else "open")
    if status not in ("open", "paid"):
        raise ValueError("status must be open or paid")
    if status == "paid" and paid is None:
        raise ValueError("paid bills need a paid date")
    raw_cat = get("category")
    category = CATEGORY_LOOKUP.get(raw_cat.strip().lower()) or guess_category("out", raw_cat, vendor)
    if category in INCOME_CATEGORIES:
        category = "Other Expense"
    bill_no = _clip(get("bill_no"), 50)
    base = (vendor.lower(), bill_no.lower() or due.isoformat(), f"{amount:.2f}")
    seen[base] += 1
    recurring = get("recurring").strip().lower() in ("yes", "y", "true", "1")
    return {"Vendor": vendor, "Category": category, "IssueDate": issue, "DueDate": due, "Amount": round(amount, 2),
            "Status": status, "PaidDate": paid if status == "paid" else None, "IsRecurring": recurring,
            "BillNo": bill_no, "VendorEmail": _clip(get("vendor_email"), 200), "DedupeKey": _sha(*base, seen[base])}


# ---------------------------------------------------------------- writing

def _read_pdf(content: bytes, kind: str, password: str, date_format: str):
    from app.pdf_statement import StatementError, read_statement

    if kind != "transactions":
        raise ImportFileError("PDF import reads bank statements. Import invoices and bills as CSV or Excel.")
    order = {"DD/MM/YYYY": "dmy", "MM/DD/YYYY": "mdy"}.get(date_format)
    try:
        return read_statement(content, password, order)
    except StatementError as e:
        raise ImportFileError(str(e)) from None


def run_import(db: Session, business_id: int, user_id: int, kind: str, file_name: str, content: bytes, *,
               dry_run: bool, date_format: str = "auto", password: str = "",
               account_id: int | None = None) -> ImportReport:
    if kind not in KINDS:
        raise ImportFileError(f"Unknown import type '{kind}'")
    if date_format not in DATE_FORMATS:
        raise ImportFileError("Unknown date format")
    statement = None
    if file_name.lower().endswith(".pdf"):
        statement = _read_pdf(content, kind, password, date_format)
        rows = statement.rows
        mapping = {"date": "date", "description": "description", "amount": "amount"}
        date_format = "auto"                      # the PDF reader already produced ISO dates
    else:
        rows = read_rows(content, file_name)
        if not rows:
            raise ImportFileError("No data rows found under the header.")
        mapping = map_columns(rows, kind)

    accounts = {a.Name.strip().lower(): a.Id for a in db.scalars(
        select(models.SmeBankAccount).where(models.SmeBankAccount.BusinessId == business_id))}
    if account_id is not None:
        if account_id not in accounts.values():
            raise ImportFileError("Choose one of your bank accounts.")
        default_account = account_id
    else:
        default_account = db.scalar(select(models.SmeBankAccount.Id).where(
            models.SmeBankAccount.BusinessId == business_id).order_by(
            (models.SmeBankAccount.AccountType != "checking"), models.SmeBankAccount.Id).limit(1))
    if kind == "transactions" and default_account is None:
        raise ImportFileError("Add a bank account before importing transactions.")

    results = convert_rows(kind, rows, mapping, date_format, accounts, default_account)
    pdf_issues = statement.issues if statement else []
    report = ImportReport(kind=kind, file_name=file_name[:200], dry_run=dry_run,
                          rows_total=len(rows) + len(pdf_issues), columns=sorted(mapping.keys()))
    if statement:
        report.warnings, report.statement = statement.warnings, statement.info
        for issue in pdf_issues:
            report.rejected += 1
            if len(report.errors) < MAX_ERRORS:
                report.errors.append({"row": 0, "label": issue["label"], "errors": issue["errors"]})
    for i, r in enumerate(results):
        if r.errors:
            report.rejected += 1
            if len(report.errors) < MAX_ERRORS:
                label = statement.labels[i] if statement else f"Row {r.row}"
                report.errors.append({"row": r.row, "label": label, "errors": r.errors})
    valid = [r.values for r in results if not r.errors]
    report.preview = [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()
                       if k not in ("DedupeKey", "AccountId")} for row in valid[:10]]

    batch = None
    if not dry_run:
        batch = models.ImportBatch(BusinessId=business_id, Kind=kind, FileName=report.file_name,
                                   RowsTotal=len(rows), CreatedBy=user_id)
        db.add(batch)
        db.flush()

    if kind == "transactions":
        _write_transactions(db, business_id, valid, report, batch)
    elif kind == "invoices":
        _write_invoices(db, business_id, valid, report, batch)
    else:
        _write_bills(db, business_id, valid, report, batch)

    if batch is not None:
        batch.RowsImported, batch.RowsDuplicate, batch.RowsRejected = report.imported + report.updated, \
            report.duplicates, report.rejected
        batch.ErrorsJson = json.dumps(report.errors)
        report.batch_id = batch.Id
        refresh_business_revenue(db, business_id)
        db.commit()
    else:
        db.rollback()
    return report


def _existing_keys(db: Session, model, business_id: int, keys: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        q = select(model.DedupeKey).where(model.DedupeKey.in_(chunk))
        if model is models.SmeTransaction:
            accts = select(models.SmeBankAccount.Id).where(models.SmeBankAccount.BusinessId == business_id)
            q = q.where(models.SmeTransaction.AccountId.in_(accts))
        else:
            q = q.where(model.BusinessId == business_id)
        found.update(db.scalars(q))
    return found


def _write_transactions(db, business_id, rows, report, batch) -> None:
    existing = _existing_keys(db, models.SmeTransaction, business_id, [r["DedupeKey"] for r in rows])
    open_invoices = {i.InvoiceNo.lower(): i for i in db.scalars(select(models.SmeInvoice).where(
        models.SmeInvoice.BusinessId == business_id, models.SmeInvoice.Status == "open"))}
    for r in rows:
        if r["DedupeKey"] in existing:
            report.duplicates += 1
            continue
        report.imported += 1
        if batch is None:
            continue
        txn = models.SmeTransaction(**r, ImportBatchId=batch.Id)
        # Link customer payments that quote an open invoice number.
        if r["Direction"] == "in" and open_invoices:
            text = f"{r['Description']} {r['Counterparty']}".lower()
            inv = next((i for no, i in open_invoices.items() if no and re.search(rf"\b{re.escape(no)}\b", text)), None)
            if inv is not None and abs(inv.Amount - r["Amount"]) <= max(0.01, inv.Amount * 0.001):
                txn.InvoiceId, txn.Counterparty = inv.Id, inv.Customer
                txn.Category = "Sales" if not txn.Category.startswith(REVENUE_PREFIX) else txn.Category
                inv.Status, inv.PaidDate = "paid", r["TxnDate"]
                open_invoices.pop(inv.InvoiceNo.lower(), None)
                report.linked_payments += 1
        db.add(txn)


def _write_invoices(db, business_id, rows, report, batch) -> None:
    existing = {i.InvoiceNo.lower(): i for i in db.scalars(select(models.SmeInvoice).where(
        models.SmeInvoice.BusinessId == business_id))}
    in_file: set[str] = set()
    for r in rows:
        key = r["InvoiceNo"].lower()
        if key in in_file:
            report.duplicates += 1
            continue
        in_file.add(key)
        current = existing.get(key)
        if current is not None:
            if (current.Status, current.PaidDate) != (r["Status"], r["PaidDate"]) or current.Amount != r["Amount"]:
                report.updated += 1
                if batch is not None:
                    current.Status, current.PaidDate, current.Amount, current.DueDate = \
                        r["Status"], r["PaidDate"], r["Amount"], r["DueDate"]
            else:
                report.duplicates += 1
            continue
        report.imported += 1
        if batch is not None:
            db.add(models.SmeInvoice(BusinessId=business_id, ImportBatchId=batch.Id, **r))


def _write_bills(db, business_id, rows, report, batch) -> None:
    existing = _existing_keys(db, models.SmeBill, business_id, [r["DedupeKey"] for r in rows])
    for r in rows:
        if r["DedupeKey"] in existing:
            report.duplicates += 1
            continue
        report.imported += 1
        if batch is not None:
            db.add(models.SmeBill(BusinessId=business_id, ImportBatchId=batch.Id, **r))


def refresh_business_revenue(db: Session, business_id: int) -> None:
    """Keep SmeBusiness.AnnualRevenue in line with the ledger (used by financing eligibility)."""
    db.flush()
    since = date.today() - timedelta(days=365)
    accts = select(models.SmeBankAccount.Id).where(models.SmeBankAccount.BusinessId == business_id)
    total = db.scalar(select(func.coalesce(func.sum(models.SmeTransaction.Amount), 0.0)).where(
        models.SmeTransaction.AccountId.in_(accts), models.SmeTransaction.Direction == "in",
        models.SmeTransaction.Category.like(f"{REVENUE_PREFIX}%"), models.SmeTransaction.TxnDate > since))
    biz = db.get(models.SmeBusiness, business_id)
    if total:
        biz.AnnualRevenue = round(float(total), 2)
