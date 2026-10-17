"""Loads one business's sandbox data into pandas DataFrames for the finance engines.

Engines are pure functions over a `Ledger`, so they can be unit-tested without a
database and always compute numbers deterministically (the LLM never does maths).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

# Category groups used across engines.
REVENUE_PREFIX = "Sales"
COGS = {"Ingredients", "Packaging", "Inventory"}
OPEX = {"Payroll", "Rent", "Utilities", "Insurance", "Software", "Marketing", "Maintenance", "Bank & Card Fees",
        "Professional Fees", "Other Expense"}
DEBT_SERVICE = {"Loan Repayment"}
TAXES = {"Taxes"}
OWNER = {"Owner Draw"}
CAPEX = {"Equipment"}
NON_OPERATING = {"Opening Balance", "Transfer"}
ASSUMED_CREDIT_SCORE = 640  # used (and disclosed) when a business has not entered its score
MIN_MONTHS_FOR_SCORE = 3    # below this, the health score is withheld as unreliable


@dataclass
class Ledger:
    as_of: pd.Timestamp
    business: models.SmeBusiness
    accounts: pd.DataFrame
    txns: pd.DataFrame       # TxnDate, Amount (>0), Direction, Signed, Category, Counterparty, InvoiceId, BillId
    invoices: pd.DataFrame   # Id, InvoiceNo, Customer, IssueDate, DueDate, Amount, Status, PaidDate, Memo
    bills: pd.DataFrame      # Id, Vendor, Category, IssueDate, DueDate, Amount, Status, PaidDate, ScheduledDate, IsRecurring
    loans: pd.DataFrame
    products: list[models.FinProduct]

    @property
    def operating_cash(self) -> float:
        """Day-to-day cash: checking accounts. A business with only savings accounts runs on those."""
        rows = self.accounts[self.accounts["AccountType"] == "checking"]
        if rows.empty:
            rows = self.accounts
        return float(rows["Balance"].sum())

    @property
    def total_cash(self) -> float:
        return float(self.accounts["Balance"].sum())

    @property
    def credit_score(self) -> int:
        """Business credit score, or a conservative assumption when the owner has not provided one."""
        return self.business.CreditScore if self.business.CreditScore is not None else ASSUMED_CREDIT_SCORE

    @property
    def credit_score_assumed(self) -> bool:
        return self.business.CreditScore is None

    @property
    def months_of_history(self) -> float:
        t = self.operating_txns()
        if t.empty:
            return 0.0
        return round((self.as_of - t["TxnDate"].min()).days / 30.44, 1)

    def walk_in_revenue(self) -> pd.DataFrame:
        """Revenue not linked to an invoice (card/cash sales); the forecast's statistical baseline."""
        t = self.txns
        return t[(t["Direction"] == "in") & t["Category"].str.startswith(REVENUE_PREFIX) & t["InvoiceId"].isna()]

    @property
    def years_in_business(self) -> float:
        return (self.as_of.date() - self.business.FoundedDate).days / 365.25

    def operating_txns(self) -> pd.DataFrame:
        return self.txns[~self.txns["Category"].isin(NON_OPERATING)]

    def window(self, days: int) -> pd.DataFrame:
        """Operating transactions in the trailing `days` days (inclusive of as_of)."""
        t = self.operating_txns()
        return t[t["TxnDate"] > self.as_of - pd.Timedelta(days=days)]


def _frame(rows, columns: list[str], date_cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame([{c: getattr(r, c) for c in columns} for r in rows], columns=columns)
    for c in date_cols:
        df[c] = pd.to_datetime(df[c])
    return df


def load_ledger(session: Session, business_id: int, as_of: date | None = None) -> Ledger:
    business = session.get(models.SmeBusiness, business_id)
    if business is None:
        raise LookupError(f"Business {business_id} not found")
    ref = pd.Timestamp(as_of or business.DataAsOf or date.today())

    accounts = session.scalars(
        select(models.SmeBankAccount).where(models.SmeBankAccount.BusinessId == business_id)).all()
    account_ids = [a.Id for a in accounts]
    txns = session.scalars(
        select(models.SmeTransaction).where(models.SmeTransaction.AccountId.in_(account_ids))).all()
    invoices = session.scalars(
        select(models.SmeInvoice).where(models.SmeInvoice.BusinessId == business_id)).all()
    bills = session.scalars(select(models.SmeBill).where(models.SmeBill.BusinessId == business_id)).all()
    loans = session.scalars(select(models.SmeLoan).where(models.SmeLoan.BusinessId == business_id)).all()
    products = list(session.scalars(select(models.FinProduct)).all())

    txn_df = _frame(txns, ["Id", "TxnDate", "Amount", "Direction", "Category", "Counterparty",
                           "Description", "InvoiceId", "BillId"], ["TxnDate"])
    txn_df["Signed"] = txn_df["Amount"].where(txn_df["Direction"] == "in", -txn_df["Amount"])
    txn_df = txn_df[txn_df["TxnDate"] <= ref].sort_values(["TxnDate", "Id"]).reset_index(drop=True)

    return Ledger(
        as_of=ref,
        business=business,
        accounts=_frame(accounts, ["Id", "Name", "AccountType", "AccountNumber", "Balance", "Currency"], []),
        txns=txn_df,
        invoices=_frame(invoices, ["Id", "InvoiceNo", "Customer", "IssueDate", "DueDate", "Amount", "Status",
                                   "PaidDate", "Memo"], ["IssueDate", "DueDate", "PaidDate"]),
        bills=_frame(bills, ["Id", "Vendor", "Category", "IssueDate", "DueDate", "Amount", "Status",
                             "PaidDate", "ScheduledDate", "IsRecurring"],
                     ["IssueDate", "DueDate", "PaidDate", "ScheduledDate"]),
        loans=_frame(loans, ["Id", "Lender", "LoanType", "Principal", "AnnualRate", "TermMonths", "StartDate",
                             "MonthlyPayment", "PaymentDay", "Outstanding"], ["StartDate"]),
        products=products,
    )


def fmt_money(x: float, currency: str = "USD") -> str:
    """$1,234 / -$1,234 for USD, BDT 1,234 / -BDT 1,234 otherwise (sign before the currency)."""
    from app.fx import fmt
    return fmt(x, currency)


def linear_score(value: float, worst: float, best: float) -> float:
    """Map value onto 0-100, where `worst` -> 0 and `best` -> 100 (works for either direction)."""
    if best == worst:
        return 100.0
    s = (value - worst) / (best - worst) * 100
    return float(max(0.0, min(100.0, s)))
