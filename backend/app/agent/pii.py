"""PII masking for everything sent to the LLM provider.

Masked (replaced by stable tokens, restored before display):
  * people's names      users of the app and person counterparties (e.g. owner draws)  -> [PERSON_1]
  * email addresses                                                                       -> [EMAIL_1]
  * bank account numbers / long digit runs (8+ digits, optionally dash-separated)          -> [ACCOUNT_1]
  * phone numbers                                                                         -> [PHONE_1]

Not masked: business names of customers and suppliers (company data the model needs to
reason about receivables and payables) and invoice/bill identifiers.

Tokens are consistent within a turn, so the model can refer to "[PERSON_1]" and the
user sees the real name in the final answer.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ACCOUNT = re.compile(r"(?<![\w-])(?:\d-?){7,18}\d(?![\w-])")  # 8+ digits; dashes only, so "40000 55000" is not an account
PHONE = re.compile(r"(?<!\w)\+?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)")
DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Masker:
    def __init__(self, person_names: list[str] | None = None):
        # Longest names first so "Maya Lin" is replaced before "Maya".
        self.people = sorted({n for n in (person_names or []) if n and len(n) > 2}, key=len, reverse=True)
        self.forward: dict[str, str] = {}
        self.reverse: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    @classmethod
    def for_business(cls, db: Session, business_id: int) -> "Masker":
        names = list(db.scalars(select(models.SmeUser.FullName).where(models.SmeUser.BusinessId == business_id)))
        # Person counterparties: owner draws are paid to a named individual.
        accounts = select(models.SmeBankAccount.Id).where(models.SmeBankAccount.BusinessId == business_id)
        names += list(db.scalars(select(models.SmeTransaction.Counterparty).distinct().where(
            models.SmeTransaction.AccountId.in_(accounts), models.SmeTransaction.Category == "Owner Draw")))
        return cls(names)

    def _token(self, kind: str, value: str) -> str:
        if value in self.forward:
            return self.forward[value]
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"[{kind}_{self._counts[kind]}]"
        self.forward[value] = token
        self.reverse[token] = value
        return token

    def mask(self, text: str) -> str:
        if not text:
            return text
        text = EMAIL.sub(lambda m: self._token("EMAIL", m.group()), text)
        text = PHONE.sub(lambda m: self._token("PHONE", m.group()), text)
        text = ACCOUNT.sub(lambda m: m.group() if DATE_LIKE.match(m.group()) else self._token("ACCOUNT", m.group()),
                           text)
        for name in self.people:
            if name in text:
                text = text.replace(name, self._token("PERSON", name))
        return text

    def unmask(self, text: str) -> str:
        if not text:
            return text
        for token, value in self.reverse.items():
            text = text.replace(token, value)
        return text

    @property
    def masked_count(self) -> int:
        return len(self.forward)
