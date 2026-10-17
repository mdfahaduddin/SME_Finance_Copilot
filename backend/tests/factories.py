"""Build small in-memory ledgers for engine unit tests (no database)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.engines.ledger import Ledger
from app.models import FinProduct, SmeBusiness

AS_OF = pd.Timestamp("2026-06-30")


class LedgerBuilder:
    def __init__(self, as_of: pd.Timestamp = AS_OF, cash: float = 50_000.0, savings: float = 0.0):
        self.as_of = as_of
        self.cash, self.savings = cash, savings
        self.txns: list[dict] = []
        self.invoices: list[dict] = []
        self.bills: list[dict] = []
        self.loans: list[dict] = []
        self.products: list[FinProduct] = []
        self.business = SmeBusiness(
            Id=1, Name="Test Co", Industry="Food & Beverage", Region="X", FoundedDate=date(2020, 1, 1),
            Employees=5, AnnualRevenue=500_000, CreditScore=700, HasCollateral=False, Currency="USD",
            DataAsOf=as_of.date(),
        )

    def txn(self, d, amount, direction, category, counterparty="Someone", invoice_id=None, bill_id=None):
        self.txns.append(dict(Id=len(self.txns) + 1, TxnDate=pd.Timestamp(d), Amount=float(amount),
                              Direction=direction, Category=category, Counterparty=counterparty,
                              Description="", InvoiceId=invoice_id, BillId=bill_id))
        return self

    def every(self, start, step_days, count, amount, direction, category, counterparty):
        d = pd.Timestamp(start)
        for _ in range(count):
            self.txn(d, amount, direction, category, counterparty)
            d += pd.Timedelta(days=step_days)
        return self

    def invoice(self, customer, issue, due, amount, status="open", paid=None):
        i = len(self.invoices) + 1
        self.invoices.append(dict(Id=i, InvoiceNo=f"INV-{i}", Customer=customer, IssueDate=pd.Timestamp(issue),
                                  DueDate=pd.Timestamp(due), Amount=float(amount), Status=status,
                                  PaidDate=pd.Timestamp(paid) if paid else pd.NaT, Memo=""))
        if status == "paid":
            self.txn(paid, amount, "in", "Sales - Catering", customer, invoice_id=i)
        return self

    def bill(self, vendor, due, amount, category="Ingredients", status="open"):
        i = len(self.bills) + 1
        self.bills.append(dict(Id=i, Vendor=vendor, Category=category,
                               IssueDate=pd.Timestamp(due) - pd.Timedelta(days=14),
                               DueDate=pd.Timestamp(due), Amount=float(amount), Status=status,
                               PaidDate=pd.NaT, ScheduledDate=pd.NaT, IsRecurring=False))
        return self

    def loan(self, outstanding=50_000, rate=0.08, payment=1_500):
        self.loans.append(dict(Id=1, Lender="Bank", LoanType="term_loan", Principal=outstanding, AnnualRate=rate,
                               TermMonths=60, StartDate=pd.Timestamp("2024-01-15"), MonthlyPayment=payment,
                               PaymentDay=15, Outstanding=outstanding))
        return self

    def product(self, **kw):
        defaults = dict(Id=len(self.products) + 1, Lender="L", Name="P", ProductType="term_loan", Description="",
                        MinAmount=1_000, MaxAmount=100_000, AprMin=0.10, AprMax=0.10, OriginationFeePct=0.0,
                        TermMonthsMin=12, TermMonthsMax=12, MinAnnualRevenue=0, MaxAnnualRevenue=None,
                        MinYearsInBusiness=0, MinCreditScore=0, RequiresCollateral=False, ExcludedIndustries="",
                        EligibleIndustries="", FundingDays=5, Purposes="working_capital,bridge,equipment")
        defaults.update(kw)
        self.products.append(FinProduct(**defaults))
        return self

    def build(self) -> Ledger:
        def df(rows, cols, dates):
            frame = pd.DataFrame(rows, columns=cols)
            for c in dates:
                frame[c] = pd.to_datetime(frame[c])
            return frame

        txns = df(self.txns, ["Id", "TxnDate", "Amount", "Direction", "Category", "Counterparty", "Description",
                              "InvoiceId", "BillId"], ["TxnDate"])
        txns["Signed"] = txns["Amount"].where(txns["Direction"] == "in", -txns["Amount"])
        accounts = pd.DataFrame([
            dict(Id=1, Name="Op", AccountType="checking", AccountNumber="1", Balance=self.cash, Currency="USD"),
            dict(Id=2, Name="Sav", AccountType="savings", AccountNumber="2", Balance=self.savings, Currency="USD"),
        ])
        return Ledger(
            as_of=self.as_of, business=self.business, accounts=accounts,
            txns=txns.sort_values(["TxnDate", "Id"]).reset_index(drop=True),
            invoices=df(self.invoices, ["Id", "InvoiceNo", "Customer", "IssueDate", "DueDate", "Amount", "Status",
                                        "PaidDate", "Memo"], ["IssueDate", "DueDate", "PaidDate"]),
            bills=df(self.bills, ["Id", "Vendor", "Category", "IssueDate", "DueDate", "Amount", "Status",
                                  "PaidDate", "ScheduledDate", "IsRecurring"],
                     ["IssueDate", "DueDate", "PaidDate", "ScheduledDate"]),
            loans=df(self.loans, ["Id", "Lender", "LoanType", "Principal", "AnnualRate", "TermMonths", "StartDate",
                                  "MonthlyPayment", "PaymentDay", "Outstanding"], ["StartDate"]),
            products=self.products,
        )


def daily_retail(b: LedgerBuilder, days: int, amount: float = 1_000.0) -> LedgerBuilder:
    start = b.as_of - pd.Timedelta(days=days - 1)
    return b.every(start, 1, days, amount, "in", "Sales - Retail", "CardPay Settlements")
