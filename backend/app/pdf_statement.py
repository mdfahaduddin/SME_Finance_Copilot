"""Reads transactions from a bank-statement PDF (the PDF a bank lets you download, not a scan).

Statements have no standard layout, so this works from the text positions on each page:

  1. Group words into lines by their vertical position.
  2. Find the column header ("Date ... Debit Credit Balance", "Date ... Amount Balance", ...) and
     remember where each money column sits horizontally. Headers repeat per page, so each page
     can update the columns.
  3. A line that starts with a date is a transaction. Its amounts are assigned to the nearest
     header column; the words between the date and the first amount are the description. Lines
     without a date and without amounts continue the previous description (wrapped text). A line
     with amounts but no date reuses the previous date (banks that print the date once per day).
  4. Reconcile against the running balance: previous balance +/- amount must equal the printed
     balance. This catches mis-read rows, and decides money in/out when the statement prints one
     unsigned amount column.

The output rows use the same keys as a CSV import ("date", "description", "amount"), so dedupe,
categorisation, preview and validation are shared with the CSV/Excel path.

Security: the PDF is untrusted input. Page count is capped, text is only read (no scripts, forms
or embedded files are touched), and the password, when given, is used to open the file only.
It is never stored or logged.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

MAX_PAGES = 100
MIN_TEXT_CHARS = 40          # less than this in the whole file -> nothing readable
MIN_PAGE_TEXT = 20           # a page with less text than this is an image (scan) and goes to OCR
LINE_TOLERANCE = 3.0         # words whose tops differ by less than this (pt) share a line
MAX_DESCRIPTION = 500

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"

# Date at the start of a line. Each pattern yields (day, month, year) groups via _date_parts.
DATE_PATTERNS = [
    ("iso", re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")),
    ("num", re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$")),
    ("num_short", re.compile(r"^(\d{1,2})/(\d{1,2})$")),   # "/" only: 12.05 is an amount
    ("dmy_text", re.compile(rf"^(\d{{1,2}})[-\s]?{MONTH_RE}[-\s,]*(\d{{2}}|\d{{4}})?$", re.I)),
    ("mdy_text", re.compile(rf"^{MONTH_RE}\s?(\d{{1,2}}),?\s*(\d{{4}})?$", re.I)),
]

# Money: 1,234.56  1234.56  (1,234.56)  -1,234.56  1,234.56-  1.234,56  with optional currency and CR/DR.
CURRENCY = r"(?:[$£€¥₹৳]|tk\.?|bdt|rs\.?|inr|usd|eur|gbp|sgd|aud|cad|myr|aed|hkd|cny)?"
AMOUNT_RE = re.compile(
    rf"^\(?[-+]?{CURRENCY}\s?[-+]?(\d{{1,3}}(?:[,.\s]\d{{3}})+|\d+)([.,]\d{{2}})\)?-?(cr|dr)?$", re.I)
CRDR_RE = re.compile(r"^(cr|dr|cr\.|dr\.)$", re.I)

HEADER_ROLES = {
    "debit": "out", "debits": "out", "withdrawal": "out", "withdrawals": "out", "dr": "out", "payments": "out",
    "credit": "in", "credits": "in", "deposit": "in", "deposits": "in", "cr": "in", "receipts": "in",
    "amount": "amount", "amt": "amount", "transaction amount": "amount",
    "balance": "balance", "bal": "balance", "running balance": "balance",
    "paid out": "out", "money out": "out", "paid in": "in", "money in": "in",
}
DATE_HEADERS = {"date", "txn date", "tran date", "transaction date", "posting date", "post date", "value date",
                "trans date", "booking date"}

OPENING_RE = re.compile(r"opening balance|balance brought forward|brought forward|balance b/?f|previous balance|"
                        r"beginning balance|balance forward", re.I)
CLOSING_RE = re.compile(r"closing balance|balance carried forward|carried forward|balance c/?f|ending balance|"
                        r"new balance", re.I)
SKIP_RE = re.compile(r"^(total|totals|sub ?total|page \d|continued|statement (period|date)|account (number|no))",
                     re.I)


class StatementError(ValueError):
    """The PDF cannot be read as a statement (scan, wrong password, no transactions...)."""


@dataclass
class StatementLine:
    page: int
    line: int
    day: date
    description: str
    amount: float | None          # signed when known
    balance: float | None
    unsigned: bool = False        # amount printed without a direction; resolved by reconciliation
    cells: list[list] = field(default_factory=list)   # description text cells: [x0, text]
    ocr: bool = False             # read from a scanned page
    explicit: bool = True         # direction printed as text (sign or Dr/Cr), not from a column or the balance
    from_column: bool = False     # direction taken from the Withdrawal/Deposit column it sits in
    check: str = "unchecked"      # balance check: ok | mismatch | unchecked

    @property
    def where(self) -> str:
        return f"Page {self.page}, line {self.line}"


@dataclass
class StatementResult:
    rows: list[dict[str, str]]
    labels: list[str]                       # "Page 2, line 14" per row, for error messages
    issues: list[dict] = field(default_factory=list)   # rows that could not be read: {label, errors}
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)


# ---------------------------------------------------------------- tokens

def parse_money(text: str) -> tuple[float, str | None] | None:
    """'1,234.56' -> (1234.56, None); '(50.00)' -> (-50.0, None); '12.00 CR' -> (12.0, 'cr')."""
    t = text.strip().replace(" ", "") if re.search(r"\d \d{3}", text) else text.strip()
    m = AMOUNT_RE.match(t)
    if not m:
        return None
    whole, frac = m.group(1), m.group(2)
    whole = re.sub(r"[,.\s]", "", whole)   # thousands separators (1,234.56 / 1.234,56 / 1 234.56)
    value = float(f"{whole}.{frac[1:]}")
    negative = t.startswith(("(", "-")) or t.endswith("-") or "-" in t[:4]
    return (-value if negative else value), (m.group(3) or "").lower() or None


def _year(y: str | None) -> int | None:
    if not y:
        return None
    n = int(y)
    return n + 2000 if n < 100 else n


def _date_parts(kind: str, m: re.Match) -> tuple[int, int, int | None, bool]:
    """-> (first, second, year, numeric) where numeric parts may still be day/month or month/day."""
    if kind == "iso":
        return int(m.group(3)), int(m.group(2)), int(m.group(1)), False      # unambiguous: day, month
    if kind in ("num", "num_short"):
        return int(m.group(1)), int(m.group(2)), _year(m.group(3)) if kind == "num" else None, True
    if kind == "dmy_text":
        return int(m.group(1)), MONTHS[m.group(2).lower()[:3]], _year(m.group(3)), False
    return int(m.group(2)), MONTHS[m.group(1).lower()[:3]], _year(m.group(3)), False   # mdy_text


def match_date(words: list[str]) -> tuple[int, tuple] | None:
    """Try the first 1-3 words as a date. -> (words used, (kind, first, second, year, numeric))."""
    for n in (3, 2, 1):
        if len(words) < n:
            continue
        text = " ".join(words[:n])
        for kind, pattern in DATE_PATTERNS:
            m = pattern.match(text)
            if m:
                try:
                    first, second, year, numeric = _date_parts(kind, m)
                except (KeyError, ValueError):
                    continue
                if 1 <= first <= 31 and 1 <= second <= 31:
                    return n, (kind, first, second, year, numeric)
    return None


# ---------------------------------------------------------------- page layout

def _group_lines(words: list[dict], tolerance: float = LINE_TOLERANCE) -> list[list[dict]]:
    """Words -> lines (top to bottom), each sorted left to right."""
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    lines: list[list[dict]] = []
    for w in words:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _lines(page) -> list[list[dict]]:
    return _group_lines(page.extract_words(x_tolerance=1.5, y_tolerance=2.5, keep_blank_chars=False,
                                           use_text_flow=False))


# OCR confuses letters and digits inside numbers: "1,2O4.5O" -> "1,204.50", "l5/O3/2026" -> "15/03/2026".
OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "S": "5",
                            "s": "5", "§": "5", "B": "8", "Z": "2", ";": ","})
OCR_NUMBERISH = re.compile(r"^([(\-+]?[$£€]?)([\dOoDQIl|Ss§BZ,;./\-]+?)([)\-]?)(cr|dr|cr\.|dr\.)?$", re.I)


def _fix_ocr_text(text: str) -> str:
    m = OCR_NUMBERISH.match(text)
    if not m or sum(c.isdigit() for c in m.group(2)) < 3:
        return text
    return f"{m.group(1)}{m.group(2).translate(OCR_DIGITS)}{m.group(3)}{m.group(4) or ''}"


def _group_ocr_rows(words: list[dict], tolerance: float) -> list[list[dict]]:
    """Group OCR words into rows by vertical centre. OCR box tops vary by several points within one printed
    row (brackets, capitals, noise), so each word joins the row whose running centre is closest."""
    rows: list[tuple[float, list[dict]]] = []          # (centre, words), kept in top-to-bottom order
    for w in sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2):
        centre = (w["top"] + w["bottom"]) / 2
        if rows and abs(centre - rows[-1][0]) <= tolerance:
            c, members = rows[-1]
            members.append(w)
            rows[-1] = ((c * (len(members) - 1) + centre) / len(members), members)
        else:
            rows.append((centre, [w]))
    return [sorted(m, key=lambda w: w["x0"]) for _, m in rows]


def _ocr_lines(words: list[dict]) -> list[list[dict]]:
    """OCR words -> lines: fix digit confusions, group rows by height, re-join numbers OCR split apart."""
    words = [w for w in words if any(c.isalnum() for c in w["text"])]   # specks read as "-", ".", "~"
    for w in words:
        w["text"] = _fix_ocr_text(w["text"])
    heights = sorted(w["bottom"] - w["top"] for w in words) or [8.0]
    median_height = heights[len(heights) // 2]
    lines = []
    for line in _group_ocr_rows(words, tolerance=max(LINE_TOLERANCE, median_height * 0.6)):
        merged: list[dict] = []
        for w in line:
            prev = merged[-1] if merged else None
            if prev and w["x0"] - prev["x1"] < 4 and parse_money(prev["text"]) is None \
                    and parse_money(prev["text"] + w["text"]) is not None:      # "1,234" ".56" -> "1,234.56"
                merged[-1] = {**prev, "text": prev["text"] + w["text"], "x1": w["x1"]}
            else:
                merged.append(dict(w))
        lines.append(merged)
    return lines


def _header_columns(line: list[dict]) -> dict[str, tuple[float, float]] | None:
    """Money columns of a header line -> {role: (x0, x1)}; None if this is not a header."""
    words = [_header_word(w["text"]) for w in line]
    joined = " ".join(words)
    if not any(h in joined for h in DATE_HEADERS):
        return None
    cols: dict[str, tuple[float, float]] = {}
    i = 0
    while i < len(line):
        pair = f"{words[i]} {words[i + 1]}" if i + 1 < len(line) else ""
        if pair in HEADER_ROLES:
            role, x0, x1, i = HEADER_ROLES[pair], line[i]["x0"], line[i + 1]["x1"], i + 2
        elif words[i] in HEADER_ROLES and HEADER_ROLES[words[i]] in ("in", "out") and i + 1 < len(line) \
                and words[i + 1] in ("amount", "amt", "amountdr", "amountcr"):
            role, x0, x1, i = HEADER_ROLES[words[i]], line[i]["x0"], line[i + 1]["x1"], i + 2
        elif words[i] in HEADER_ROLES:
            role, x0, x1, i = HEADER_ROLES[words[i]], line[i]["x0"], line[i]["x1"], i + 1
        else:
            i += 1
            continue
        cols.setdefault(role, (x0, x1))
    money = set(cols) - {"balance"}
    return cols if money or ("balance" in cols and len(cols) > 1) else None


HEADER_VOCABULARY = sorted({w for key in list(HEADER_ROLES) + list(DATE_HEADERS) for w in key.split()} |
                           {"particulars", "description", "details", "narration"})


def _header_word(text: str) -> str:
    """'Balance.' / '(Dr)' / '__Value' / '“Txn' / 'Withdrawai' -> 'balance' / 'dr' / 'value' / 'txn' / 'withdrawal'.

    Strips punctuation and OCR debris; longer words that are one or two letters off a known header word
    (a common OCR result) are corrected to it.
    """
    from difflib import get_close_matches

    word = re.sub(r"[^a-z/]", "", text.lower()).strip("/")
    if len(word) >= 5 and word not in HEADER_VOCABULARY:
        close = get_close_matches(word, HEADER_VOCABULARY, n=1, cutoff=0.75)
        if close:
            return close[0]
    return word


def _headerish(line: list[dict]) -> bool:
    words = {_header_word(w["text"]) for w in line}
    return bool(words & (set(HEADER_ROLES) | {"date", "particulars", "description", "details", "narration"}))


def _cells(words: list[dict]) -> list[tuple[float, str]]:
    """Split a run of words into table cells wherever the horizontal gap is wide."""
    cells: list[tuple[float, str]] = []
    for w in words:
        if cells and w["x0"] - last_x1 < 12:
            cells[-1] = (cells[-1][0], f"{cells[-1][1]} {w['text']}")
        else:
            cells.append((w["x0"], w["text"]))
        last_x1 = w["x1"]
    return cells


def _nearest(cols: dict[str, tuple[float, float]], x0: float, x1: float) -> str:
    """Column whose header lines up with the value: by left edge, right edge or centre, whichever is closest."""
    def distance(span: tuple[float, float]) -> float:
        return min(abs(span[0] - x0), abs(span[1] - x1), abs((span[0] + span[1]) / 2 - (x0 + x1) / 2))
    return min(cols, key=lambda r: distance(cols[r]))


# ---------------------------------------------------------------- main entry

def read_statement(content: bytes, password: str = "", date_order: str | None = None) -> StatementResult:
    """date_order: None (detect), 'dmy' or 'mdy' for numeric dates such as 03/04/2026."""
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect

    try:
        pdf = pdfplumber.open(io.BytesIO(content), password=password or None)
        pages = pdf.pages
    except Exception as e:  # noqa: BLE001 - pdfplumber wraps pdfminer errors
        cause = e.__cause__ or e.__context__ or e
        if isinstance(e, PDFPasswordIncorrect) or isinstance(cause, PDFPasswordIncorrect) \
                or "PDFPasswordIncorrect" in repr(e):
            raise StatementError("The password is not correct for this PDF." if password else
                                 "This PDF is password-protected. Enter its password and check again.") from None
        raise StatementError("Could not read this PDF. Make sure it is the statement file from your bank.") from None

    with pdf:
        if len(pages) > MAX_PAGES:
            raise StatementError(f"Statements are limited to {MAX_PAGES} pages. Split the file and import each part.")
        page_lines: dict[int, list[list[dict]]] = {}
        scanned: list[int] = []
        for p, page in enumerate(pages, start=1):
            lines = _lines(page)
            if _is_scan(page, sum(len(w["text"]) for line in lines for w in line)):
                scanned.append(p)                     # an image of the page: needs OCR
            else:
                page_lines[p] = lines

    warnings: list[str] = []
    if scanned:
        page_lines.update(_ocr_scanned_pages(content, password, scanned, has_text=bool(page_lines), warnings=warnings))
    if sum(len(w["text"]) for lines in page_lines.values() for line in lines for w in line) < MIN_TEXT_CHARS:
        raise StatementError("No readable text was found in this PDF. If it is a photo or a poor scan, download the "
                             "statement from your online banking (PDF or CSV) instead.")

    raw = [(p, n, line) for p in sorted(page_lines) for n, line in enumerate(page_lines[p], start=1)]
    ocr_pages = [p for p in scanned if p in page_lines]
    result = _parse_lines(raw, date_order, frozenset(ocr_pages))
    result.warnings = warnings + result.warnings
    result.info["ocrPages"] = ocr_pages
    if ocr_pages:
        result.warnings.insert(0, f"{_pages_text(ocr_pages)} read from a scan with OCR. OCR can misread figures: "
                                  f"compare the preview with the statement before importing.")
    return result


def _is_scan(page, text_chars: int) -> bool:
    """No text layer, or a page-sized image with only a little text (a bank stamp or footer on a scan)."""
    if not page.images:
        return False
    if text_chars < MIN_PAGE_TEXT:
        return True
    area = float(page.width * page.height) or 1.0
    covered = sum(abs((i["x1"] - i["x0"]) * (i["bottom"] - i["top"])) for i in page.images)
    return covered / area > 0.6 and text_chars < 200


def _pages_text(pages: list[int]) -> str:
    return f"Page {pages[0]} was" if len(pages) == 1 else f"{len(pages)} pages were"


def _ocr_scanned_pages(content: bytes, password: str, scanned: list[int], *, has_text: bool,
                       warnings: list[str]) -> dict[int, list[list[dict]]]:
    from app import ocr
    from app.config import get_settings

    if not ocr.available():
        if not has_text:
            raise StatementError("This PDF is a scan, and reading scans (OCR) is not enabled on this server. "
                                 "Download the statement from your online banking (PDF or CSV) instead.")
        warnings.append(f"{_pages_text(scanned)} scanned images and could not be read (OCR is not enabled).")
        return {}
    limit = get_settings().ocr_max_pages
    if len(scanned) > limit:
        raise StatementError(f"Scanned statements are limited to {limit} pages. Split the file and import each part.")
    try:
        words = ocr.ocr_pdf_pages(content, password, scanned)
    except ocr.OcrError as e:
        raise StatementError(str(e)) from None
    return {p: _ocr_lines(w) for p, w in words.items() if w}


def _parse_lines(raw: list[tuple[int, int, list[dict]]], date_order: str | None,
                 ocr_pages: frozenset[int] = frozenset()) -> StatementResult:
    cols: dict[str, tuple[float, float]] | None = None
    entries: list[tuple[StatementLine, tuple | None]] = []   # (line, raw date parts or None = previous date)
    opening = closing = None
    issues: list[dict] = []
    seen_header = False
    header_part: tuple[int, list[dict], float] | None = None
    trailing_bf: float | None = None
    last_bottom: tuple[int, float] | None = None
    years = Counter()

    for page, n, line in raw:
        texts = [w["text"] for w in line]
        joined = " ".join(texts)
        for y in re.findall(r"\b(20\d{2})\b", joined):
            years[int(y)] += 1

        header = _header_columns(line)
        if not header and header_part and header_part[0] == page and line[0]["top"] - header_part[2] < 12:
            # OCR often splits a header row in two (cells a few points apart): try the two halves together.
            header = _header_columns(sorted(header_part[1] + line, key=lambda w: w["x0"]))
        header_part = (page, line, line[0]["top"]) if _headerish(line) and not header else None
        if header:
            cols, seen_header, last_bottom = header, True, None
            continue

        found = match_date(texts)
        start = found[0] if found else 0
        if found:
            second = match_date(texts[start:])          # value date / posting date column
            if second and parse_money(texts[start]) is None:
                start += second[0]
        # With a known header, numbers left of the money columns are part of the description.
        money_left = min(c[0] for c in cols.values()) - 45 if cols else None
        money: list[tuple[float, str | None, float, float]] = []   # (value, cr/dr, x0, x1)
        desc_words: list[dict] = []
        i = start
        while i < len(line):
            w = line[i]
            if i + 1 < len(line) and CRDR_RE.match(line[i + 1]["text"]):   # "1,234.56 CR" as two words
                suffixed = parse_money(w["text"] + line[i + 1]["text"].rstrip("."))
                if suffixed:
                    money.append((suffixed[0], suffixed[1], w["x0"], w["x1"]))
                    i += 2
                    continue
            parsed = parse_money(w["text"])
            if parsed is not None and money_left is not None and (w["x0"] + w["x1"]) / 2 < money_left:
                parsed = None
            if parsed is not None and (money or desc_words or found):
                money.append((parsed[0], parsed[1], w["x0"], w["x1"]))
            elif not money:
                desc_words.append(w)
            elif not CRDR_RE.match(w["text"]):
                desc_words.append(w)                           # text after an amount (rare): keep it
            i += 1
        description = " ".join(w["text"] for w in desc_words).strip()

        # Opening / closing balance lines carry a balance, not a transaction.
        if money and OPENING_RE.search(joined):
            # Only before the first transaction is it the statement's opening balance; banks also print
            # "balance brought forward" at the top of every page.
            if opening is None and not entries:
                opening = _signed_balance(money[-1])
            elif entries:
                trailing_bf = _signed_balance(money[-1])   # the opening, if the statement runs newest first
            continue
        if money and CLOSING_RE.search(joined):
            closing = _signed_balance(money[-1])
            continue
        if SKIP_RE.match(joined) or (not found and not money and not entries):
            continue

        if found and not money and entries and description:
            issues.append({"label": f"Page {page}, line {n}", "errors": [
                f"a transaction ({description[:40]}) was found but no amount could be read"]})
            continue
        if not money:
            # Wrapped description: directly below the previous transaction and not a footer.
            if entries and not found and last_bottom and last_bottom[0] == page \
                    and line[0]["top"] - last_bottom[1] < 14 and description:
                prev = entries[-1][0]
                # Each wrapped cell joins the cell above it, so a reference column stays at the end.
                for x0, text in _cells(desc_words):
                    if prev.cells:
                        min(prev.cells, key=lambda c: abs(c[0] - x0))[1] += " " + text
                    else:
                        prev.cells.append([x0, text])
                prev.description = " ".join(c[1] for c in prev.cells)[:MAX_DESCRIPTION]
                last_bottom = (page, line[0]["bottom"])
            continue
        if not found and not (entries and description and seen_header):
            continue                                          # stray numbers (totals, summaries)

        try:
            amount, balance, unsigned, from_column = _assign(money, cols)
        except ValueError as e:
            issues.append({"label": f"Page {page}, line {n}", "errors": [str(e)]})
            continue
        entries.append((StatementLine(page, n, date.min, description or "-", amount, balance, unsigned,
                                      [list(c) for c in _cells(desc_words)], ocr=page in ocr_pages,
                                      explicit=not unsigned and not from_column, from_column=from_column),
                        found[1] if found else None))
        last_bottom = (page, line[0]["bottom"])
        trailing_bf = None                                    # a later transaction: not the end after all

    if not entries:
        raise StatementError("No transactions were found in this PDF. If it is a bank statement, try the CSV or "
                             "Excel export from your online banking instead.")

    _resolve_dates(entries, date_order, years)
    stmt = [e for e, _ in entries]
    if opening is None and trailing_bf is not None and len(stmt) > 1 and stmt[0].day > stmt[-1].day:
        opening = trailing_bf
    result = StatementResult(rows=[], labels=[], issues=issues)
    _reconcile(stmt, opening, result)

    # Only directions printed on the statement count here, not ones inferred from the balance.
    if any(s.amount is not None and s.amount < 0 and s.explicit for s in stmt):
        for s in stmt:
            if s.unsigned:          # outflows are marked elsewhere in this statement, so unmarked = money in
                s.amount, s.unsigned = abs(s.amount), False

    trusted = _ocr_policy(stmt, opening, result)
    for s in stmt:
        if s.amount is None or s.unsigned:
            result.issues.append({"label": s.where, "errors": [
                "could not tell whether this is money in or out (no balance to check against)"]})
            continue
        if s.ocr and not trusted(s):
            # A misread figure must never be imported silently: leave it out and say where it is.
            problem = "doesn't match" if s.check == "mismatch" else "could not be checked against"
            result.issues.append({"label": s.where, "errors": [
                f"OCR read {s.amount:,.2f} on {s.day:%d %b %Y}, which {problem} the balance printed on the "
                f"statement. Add this transaction by hand if it is right, or import a clearer scan."]})
            continue
        result.rows.append({"date": s.day.isoformat(), "description": s.description, "amount": f"{s.amount:.2f}"})
        result.labels.append(s.where)

    days = [s.day for s in stmt]
    result.info.update({"pages": max(p for p, _, _ in raw), "transactions": len(result.rows),
                        "periodStart": min(days).isoformat(), "periodEnd": max(days).isoformat(),
                        "openingBalance": opening, "closingBalance": closing,
                        "layout": "columns" if cols else "inferred"})
    if closing is None and stmt and stmt[-1].balance is not None:
        result.info["closingBalance"] = stmt[-1].balance if days[0] <= days[-1] else stmt[0].balance
    _total_check(stmt, opening, result)
    return result


OCR_MIN_VERIFIED_SHARE = 0.6


def _ocr_policy(stmt: list[StatementLine], opening: float | None, result: StatementResult):
    """Which OCR rows may be imported. -> predicate(row) -> bool.

    With a running balance on the statement, an OCR row is imported only when the balance confirms it.
    The first row is the exception when no opening balance was found (nothing can confirm it): it is
    imported and named in a warning. If too few rows can be confirmed, the scan is refused as unreadable.
    Statements without any balance column cannot be checked: everything is imported with a warning.
    """
    ocr_rows = [s for s in stmt if s.ocr and s.amount is not None and not s.unsigned]
    if not ocr_rows:
        return lambda s: True
    if not any(s.balance is not None for s in stmt if s.ocr):
        result.warnings.append("This scan has no running balance to check the figures against. Compare every "
                               "row in the preview with the statement before importing.")
        return lambda s: True

    chronological = list(reversed(stmt)) if len(stmt) > 1 and stmt[0].day > stmt[-1].day else stmt
    opening_known = opening is not None and not result.info.get("openingSuspect")
    first = None if opening_known else chronological[0]
    all_ocr = [s for s in stmt if s.ocr]
    verified = sum(1 for s in all_ocr if s.check == "ok")
    if verified < OCR_MIN_VERIFIED_SHARE * len(all_ocr):
        raise StatementError(
            f"This scan is too unclear to read reliably: only {verified} of {len(all_ocr)} transactions could be "
            f"confirmed against the running balance. Scan the statement again at 300 dpi (black and white or "
            f"greyscale, straight), or download the PDF from your online banking.")
    if first is not None and first.ocr and first.check != "ok":
        why = ("the opening balance on the scan looks misread" if result.info.get("openingSuspect")
               else "no opening balance was found")
        result.warnings.append(f"The first transaction ({first.where}, {first.day:%d %b}) could not be checked "
                               f"because {why}. Compare it with the statement.")
    return lambda s: s.check == "ok" or s is first


def _total_check(stmt: list[StatementLine], opening: float | None, result: StatementResult) -> None:
    """Opening balance + every imported row must equal the closing balance; catches rows that were missed."""
    chronological = list(reversed(stmt)) if len(stmt) > 1 and stmt[0].day > stmt[-1].day else stmt
    first = chronological[0]
    start = None if result.info.get("openingSuspect") else opening
    if start is None and first.balance is not None and first.amount is not None and not first.unsigned:
        start = round(first.balance - first.amount, 2)
    end = result.info.get("closingBalance")
    if start is None or end is None:
        return
    expected = round(end - start, 2)
    imported = round(sum(float(r["amount"]) for r in result.rows), 2)
    result.info["totalCheck"] = {"expected": expected, "imported": imported,
                                 "difference": round(expected - imported, 2)}
    if abs(expected - imported) >= 0.011:
        result.warnings.append(
            f"The imported rows change the balance by {imported:,.2f}, but the statement's balances changed by "
            f"{expected:,.2f} (a difference of {expected - imported:,.2f}). Some transactions were missed or "
            f"misread: compare the statement with the preview.")


def _signed_balance(token: tuple) -> float:
    value, crdr = token[0], token[1]
    return -abs(value) if crdr == "dr" else value


def _assign(money: list[tuple], cols: dict[str, tuple[float, float]] | None):
    """-> (amount, balance or None, unsigned, direction taken from the column)."""
    amount = balance = None
    unsigned = from_column = False
    if cols:
        right_edge = max(c[1] for c in cols.values())
        for value, crdr, x0, x1 in money:
            role = _nearest(cols, x0, x1)
            if "balance" not in cols and len(money) >= 2 and (x0, x1) == money[-1][2:] and (x0 + x1) / 2 > right_edge:
                role = "balance"          # header's "Balance" was unreadable, but the column is there
            if role == "balance":
                balance = -abs(value) if crdr == "dr" else value
            elif role == "out":
                if amount is None:
                    amount, from_column = -abs(value), crdr is None and value >= 0
            elif role == "in":
                if amount is None:
                    amount, from_column = abs(value), crdr is None and value >= 0
            else:  # single amount column
                if crdr == "dr" or value < 0:
                    amount = -abs(value)
                elif crdr == "cr":
                    amount = abs(value)
                else:
                    amount, unsigned = value, True
        if amount is None and balance is not None and len(money) == 1:
            raise ValueError("no amount could be read on this line, only a balance")
    else:
        # No header: the last number is the running balance when there are two or more.
        *rest, last = money
        if rest:
            balance = _signed_balance(last)
            value, crdr = rest[-1][0], rest[-1][1]
        else:
            value, crdr = last[0], last[1]
        if crdr == "dr" or value < 0:
            amount = -abs(value)
        elif crdr == "cr":
            amount = abs(value)
        else:
            amount, unsigned = value, True
    if amount is None:
        raise ValueError("no amount found on this line")
    if amount == 0:
        raise ValueError("amount is zero")
    return amount, balance, unsigned, from_column


def _resolve_dates(entries: list[tuple[StatementLine, tuple | None]], date_order: str | None,
                   years: Counter) -> None:
    parts = [p for _, p in entries if p]
    if not parts:
        raise StatementError("No transaction dates were found in this PDF.")
    numeric = [p for p in parts if p[4]]
    order = date_order
    if order is None and numeric:
        if any(p[1] > 12 for p in numeric):
            order = "dmy"
        elif any(p[2] > 12 for p in numeric):
            order = "mdy"
        elif all(p[1] == p[2] for p in numeric):
            order = "dmy"
        else:
            raise StatementError("The dates in this statement could be day/month or month/day. Choose the date "
                                 "format and check again.")
    base_year = years.most_common(1)[0][0] if years else date.today().year

    prev: date | None = None
    for line, p in entries:
        if p is None:                       # date printed once per day: reuse the previous one
            line.day = prev
            continue
        kind, first, second, year, is_numeric = p
        day, month = (second, first) if is_numeric and order == "mdy" else (first, second)
        if year is None:
            year = base_year
            # Statements without years that cross New Year: Dec lines belong to the earlier year.
            if prev and prev.month == 12 and month == 1:
                year = prev.year + 1
            elif prev and prev.month == 1 and month == 12:
                year = prev.year - 1
        try:
            line.day = date(year, month, day)
        except ValueError:
            raise StatementError(f"'{first}/{second}' on page {line.page} is not a valid date. Choose the date format "
                                 f"and check again.") from None
        prev = line.day


def _reconcile(stmt: list[StatementLine], opening: float | None, result: StatementResult) -> None:
    """Follow the running balance through the statement and mark each row ok / mismatch / unchecked.

    * expected balance = last trusted balance + this amount; a printed balance that matches confirms the row
      (and any rows before it whose balance was not printed or not readable)
    * an unsigned amount takes its direction from the balance change
    * when a printed balance is off but the next row confirms the chain, the balance was misread, not the
      amount: both rows are fine (one bad digit in a balance should not reject two good rows)
    """
    if not any(s.balance is not None for s in stmt):
        return
    ordered = list(reversed(stmt)) if len(stmt) > 1 and stmt[0].day > stmt[-1].day else stmt
    running = opening
    pending: list[StatementLine] = []        # passed without a usable printed balance, awaiting confirmation

    def settle(rows: list[StatementLine], status: str) -> None:
        for r in rows:
            r.check = status

    for i, s in enumerate(ordered):
        if running is None:                  # no opening balance: the first printed balance anchors the chain
            settle(pending + [s], "unchecked")
            pending = []
            running = s.balance
            continue
        if s.unsigned:
            if s.balance is not None and abs(abs(s.balance - running) - abs(s.amount)) < 0.011:
                s.amount, s.unsigned = (abs(s.amount) if s.balance > running else -abs(s.amount)), False
            else:                            # direction unknown: the chain cannot continue through this row
                settle(pending + [s], "unchecked")
                pending, running = [], s.balance
                continue
        if s.from_column and s.balance is not None and abs(s.balance - running + s.amount) < 0.011:
            s.amount = -s.amount             # column geometry was wrong (common in OCR); the balance is not
        expected = round(running + s.amount, 2)
        if s.balance is None:
            pending.append(s)
            running = expected
            continue
        if abs(s.balance - expected) < 0.011:
            settle(pending + [s], "ok")
            running = s.balance
        else:
            nxt = ordered[i + 1] if i + 1 < len(ordered) else None
            nxt_fits = nxt is not None and nxt.balance is not None and not nxt.unsigned
            if nxt_fits and abs(nxt.balance - (expected + nxt.amount)) < 0.011:
                settle(pending + [s], "ok")  # this row's balance was misread; its amount fits the chain
                running = expected
            elif i == 0 and opening is not None and nxt_fits and abs(nxt.balance - (s.balance + nxt.amount)) < 0.011:
                # The chain holds from this row on, so the opening balance was misread (or mislabelled).
                settle([s], "unchecked")
                result.info["openingSuspect"] = True
                running = s.balance
            else:
                settle(pending + [s], "mismatch")
                running = s.balance
        pending = []
    settle(pending, "unchecked")

    counts = Counter(s.check for s in stmt)
    where = [f"{s.where} ({s.day:%d %b})" for s in ordered if s.check == "mismatch"]
    result.info.update({"reconciledRows": counts["ok"], "mismatchedRows": counts["mismatch"],
                        "uncheckedRows": counts["unchecked"], "mismatchedAt": where[:20]})
    if where:
        shown = ", ".join(where[:5]) + (f" and {len(where) - 5} more" if len(where) > 5 else "")
        result.warnings.append(f"{len(where)} of {len(stmt)} rows don't add up to the running balance printed on "
                               f"the statement ({shown}). Compare them with the PDF before importing.")
