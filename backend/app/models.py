"""SQLAlchemy models.

Table names follow the team's PascalCase convention. The schema is portable: SQLite for
development and tests, PostgreSQL in production (managed with Alembic migrations).
"""
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Money: DECIMAL(18,2) in the database, float in Python (engines use pandas/numpy).
Money = Numeric(18, 2, asdecimal=False)
Rate = Numeric(9, 4, asdecimal=False)


def utcnow() -> datetime:
    """Naive UTC timestamp. All DateTime columns store UTC without an offset (SQLite drops offsets)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SmeBusiness(Base):
    __tablename__ = "SmeBusiness"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    Name: Mapped[str] = mapped_column(String(200))
    Industry: Mapped[str] = mapped_column(String(100))
    Region: Mapped[str] = mapped_column(String(100))
    FoundedDate: Mapped[date] = mapped_column(Date)
    Employees: Mapped[int] = mapped_column(Integer)
    AnnualRevenue: Mapped[float] = mapped_column(Money, default=0)  # self-reported; refreshed from the ledger
    CreditScore: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 300-850; None = not provided
    HasCollateral: Mapped[bool] = mapped_column(Boolean, default=False)
    Currency: Mapped[str] = mapped_column(String(3), default="USD")
    # Fixed reference "today" for sandbox/demo data. None = use the real current date.
    DataAsOf: Mapped[date | None] = mapped_column(Date, nullable=True)
    OnboardingStatus: Mapped[str] = mapped_column(String(20), default="complete")  # profile | data | complete
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=lambda: utcnow())

    Users: Mapped[list["SmeUser"]] = relationship(back_populates="Business")

    @property
    def today(self) -> date:
        """The business's reference date: fixed for sandbox data, otherwise the real current date."""
        return self.DataAsOf or date.today()
    Accounts: Mapped[list["SmeBankAccount"]] = relationship(back_populates="Business")


class SmeUser(Base):
    __tablename__ = "SmeUser"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    Email: Mapped[str] = mapped_column(String(200), unique=True)
    FullName: Mapped[str] = mapped_column(String(200))
    PasswordHash: Mapped[str] = mapped_column(String(200))
    Role: Mapped[str] = mapped_column(String(20))  # owner | accountant | viewer
    IsActive: Mapped[bool] = mapped_column(Boolean, default=True)
    MfaSecretEnc: Mapped[str | None] = mapped_column(String(300), nullable=True)  # TOTP secret, encrypted
    MfaEnabled: Mapped[bool] = mapped_column(Boolean, default=False)
    PasswordChangedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    LastLoginAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=lambda: utcnow())

    Business: Mapped[SmeBusiness] = relationship(back_populates="Users")


class SmeBankAccount(Base):
    __tablename__ = "SmeBankAccount"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    Name: Mapped[str] = mapped_column(String(100))
    AccountType: Mapped[str] = mapped_column(String(20))  # checking | savings
    AccountNumber: Mapped[str] = mapped_column(String(34))  # PII - masked before LLM
    Balance: Mapped[float] = mapped_column(Money)
    Currency: Mapped[str] = mapped_column(String(3), default="USD")

    Business: Mapped[SmeBusiness] = relationship(back_populates="Accounts")


class SmeTransaction(Base):
    __tablename__ = "SmeTransaction"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    AccountId: Mapped[int] = mapped_column(ForeignKey("SmeBankAccount.Id"), index=True)
    TxnDate: Mapped[date] = mapped_column(Date, index=True)
    Amount: Mapped[float] = mapped_column(Money)  # always positive; see Direction
    Direction: Mapped[str] = mapped_column(String(3))  # in | out
    Category: Mapped[str] = mapped_column(String(50), index=True)
    Counterparty: Mapped[str] = mapped_column(String(200))
    Description: Mapped[str] = mapped_column(String(500), default="")
    InvoiceId: Mapped[int | None] = mapped_column(ForeignKey("SmeInvoice.Id"), nullable=True)
    BillId: Mapped[int | None] = mapped_column(ForeignKey("SmeBill.Id"), nullable=True)
    ImportBatchId: Mapped[int | None] = mapped_column(ForeignKey("ImportBatch.Id"), nullable=True)
    DedupeKey: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # re-import protection


class SmeInvoice(Base):
    """Accounts receivable: money customers owe the business."""
    __tablename__ = "SmeInvoice"
    __table_args__ = (UniqueConstraint("BusinessId", "InvoiceNo", name="UQ_SmeInvoice_Business_InvoiceNo"),)

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    InvoiceNo: Mapped[str] = mapped_column(String(30))
    Customer: Mapped[str] = mapped_column(String(200), index=True)
    CustomerEmail: Mapped[str] = mapped_column(String(200), default="")  # PII
    IssueDate: Mapped[date] = mapped_column(Date)
    DueDate: Mapped[date] = mapped_column(Date, index=True)
    Amount: Mapped[float] = mapped_column(Money)
    Status: Mapped[str] = mapped_column(String(10))  # open | paid | void
    PaidDate: Mapped[date | None] = mapped_column(Date, nullable=True)
    Memo: Mapped[str] = mapped_column(String(500), default="")  # untrusted free text
    ImportBatchId: Mapped[int | None] = mapped_column(ForeignKey("ImportBatch.Id"), nullable=True)


class SmeBill(Base):
    """Accounts payable: money the business owes vendors."""
    __tablename__ = "SmeBill"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    Vendor: Mapped[str] = mapped_column(String(200))
    Category: Mapped[str] = mapped_column(String(50))
    IssueDate: Mapped[date] = mapped_column(Date)
    DueDate: Mapped[date] = mapped_column(Date, index=True)
    Amount: Mapped[float] = mapped_column(Money)
    Status: Mapped[str] = mapped_column(String(10))  # open | paid | scheduled
    PaidDate: Mapped[date | None] = mapped_column(Date, nullable=True)
    ScheduledDate: Mapped[date | None] = mapped_column(Date, nullable=True)  # set when a payment is scheduled
    IsRecurring: Mapped[bool] = mapped_column(Boolean, default=False)
    BillNo: Mapped[str] = mapped_column(String(50), default="")  # vendor's reference, when known
    VendorEmail: Mapped[str] = mapped_column(String(200), default="")  # PII
    ImportBatchId: Mapped[int | None] = mapped_column(ForeignKey("ImportBatch.Id"), nullable=True)
    DedupeKey: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class SmeLoan(Base):
    """Existing debt."""
    __tablename__ = "SmeLoan"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    Lender: Mapped[str] = mapped_column(String(200))
    LoanType: Mapped[str] = mapped_column(String(30))
    Principal: Mapped[float] = mapped_column(Money)
    AnnualRate: Mapped[float] = mapped_column(Rate)  # 0.085 = 8.5%
    TermMonths: Mapped[int] = mapped_column(Integer)
    StartDate: Mapped[date] = mapped_column(Date)
    MonthlyPayment: Mapped[float] = mapped_column(Money)
    PaymentDay: Mapped[int] = mapped_column(Integer)  # day of month
    Outstanding: Mapped[float] = mapped_column(Money)


class FinProduct(Base):
    """Mock lender marketplace catalogue."""
    __tablename__ = "FinProduct"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    Lender: Mapped[str] = mapped_column(String(200))
    Name: Mapped[str] = mapped_column(String(200))
    ProductType: Mapped[str] = mapped_column(String(30))  # term_loan | credit_line | invoice_finance | equipment | merchant_advance | gov_grant
    Description: Mapped[str] = mapped_column(String(500))
    MinAmount: Mapped[float] = mapped_column(Money)
    MaxAmount: Mapped[float] = mapped_column(Money)
    AprMin: Mapped[float] = mapped_column(Rate)
    AprMax: Mapped[float] = mapped_column(Rate)
    OriginationFeePct: Mapped[float] = mapped_column(Rate, default=0)
    TermMonthsMin: Mapped[int] = mapped_column(Integer)
    TermMonthsMax: Mapped[int] = mapped_column(Integer)
    MinAnnualRevenue: Mapped[float] = mapped_column(Money, default=0)
    MaxAnnualRevenue: Mapped[float | None] = mapped_column(Money, nullable=True)  # e.g. small-business grants
    MinYearsInBusiness: Mapped[float] = mapped_column(Numeric(4, 1, asdecimal=False), default=0)
    MinCreditScore: Mapped[int] = mapped_column(Integer, default=0)
    RequiresCollateral: Mapped[bool] = mapped_column(Boolean, default=False)
    ExcludedIndustries: Mapped[str] = mapped_column(String(500), default="")  # comma separated
    EligibleIndustries: Mapped[str] = mapped_column(String(500), default="")  # empty = all
    FundingDays: Mapped[int] = mapped_column(Integer)  # typical time to funds
    Purposes: Mapped[str] = mapped_column(String(200))  # comma separated: working_capital,equipment,expansion,bridge
    # Currency of the amount limits above (MinAmount, MaxAmount, revenue bounds). Converted for each business.
    Currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")


class SmeAlert(Base):
    __tablename__ = "SmeAlert"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    AlertType: Mapped[str] = mapped_column(String(50))
    Severity: Mapped[str] = mapped_column(String(10))  # critical | high | medium | low
    Title: Mapped[str] = mapped_column(String(200))
    Detail: Mapped[str] = mapped_column(Text)
    SuggestedAction: Mapped[str] = mapped_column(Text, default="")
    Fingerprint: Mapped[str] = mapped_column(String(100), index=True)  # de-duplicate repeat alerts
    Status: Mapped[str] = mapped_column(String(15), default="open")  # open | acknowledged | resolved
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentActionRequest(Base):
    """Human-in-the-loop approval queue for tier-2 (action) tools."""
    __tablename__ = "AgentActionRequest"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    Tool: Mapped[str] = mapped_column(String(100))
    Summary: Mapped[str] = mapped_column(String(300), default="")  # human-readable one-liner for the approval card
    RequestedVia: Mapped[str] = mapped_column(String(10), default="ui")  # ui | agent
    ParamsJson: Mapped[str] = mapped_column(Text)
    Rationale: Mapped[str] = mapped_column(Text, default="")
    RiskLevel: Mapped[str] = mapped_column(String(10), default="medium")
    Amount: Mapped[float | None] = mapped_column(Money, nullable=True)
    Status: Mapped[str] = mapped_column(String(15), default="pending")  # pending | approved | rejected | executed | expired | failed
    IdempotencyKey: Mapped[str] = mapped_column(String(100), unique=True)
    RequestedBy: Mapped[int] = mapped_column(ForeignKey("SmeUser.Id"))
    DecidedBy: Mapped[int | None] = mapped_column(ForeignKey("SmeUser.Id"), nullable=True)
    DecisionReason: Mapped[str] = mapped_column(Text, default="")
    ResultJson: Mapped[str] = mapped_column(Text, default="")
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    DecidedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ExpiresAt: Mapped[datetime] = mapped_column(DateTime)


class SmeOutboxMessage(Base):
    """Simulated outgoing messages (reminders, lender submissions). Nothing is actually sent."""
    __tablename__ = "SmeOutboxMessage"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    ActionRequestId: Mapped[int | None] = mapped_column(ForeignKey("AgentActionRequest.Id"), nullable=True)
    Channel: Mapped[str] = mapped_column(String(20), default="email")
    Recipient: Mapped[str] = mapped_column(String(200))  # PII
    Subject: Mapped[str] = mapped_column(String(300))
    Body: Mapped[str] = mapped_column(Text)
    Status: Mapped[str] = mapped_column(String(15), default="simulated")
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoanApplication(Base):
    __tablename__ = "LoanApplication"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    ProductId: Mapped[int] = mapped_column(ForeignKey("FinProduct.Id"))
    Amount: Mapped[float] = mapped_column(Money)
    TermMonths: Mapped[int] = mapped_column(Integer)
    Purpose: Mapped[str] = mapped_column(String(500))
    Status: Mapped[str] = mapped_column(String(15), default="draft")  # draft | submitted | approved | declined
    PayloadJson: Mapped[str] = mapped_column(Text, default="{}")
    ReferenceNo: Mapped[str] = mapped_column(String(40), default="")
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    SubmittedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatSession(Base):
    __tablename__ = "ChatSession"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    UserId: Mapped[int] = mapped_column(ForeignKey("SmeUser.Id"))
    Title: Mapped[str] = mapped_column(String(200), default="New conversation")
    PinnedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # set = pinned to the top of the list
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChatMessage(Base):
    __tablename__ = "ChatMessage"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    SessionId: Mapped[int] = mapped_column(ForeignKey("ChatSession.Id"), index=True)
    Role: Mapped[str] = mapped_column(String(15))  # user | assistant
    Content: Mapped[str] = mapped_column(Text)
    ToolTraceJson: Mapped[str] = mapped_column(Text, default="[]")
    MetaJson: Mapped[str] = mapped_column(Text, default="{}")  # mode, groundedness, approval ids, PII count
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserSession(Base):
    """Server-side session. The browser holds only a random token in an HttpOnly cookie; we store its hash."""
    __tablename__ = "UserSession"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    UserId: Mapped[int] = mapped_column(ForeignKey("SmeUser.Id"), index=True)
    TokenHash: Mapped[str] = mapped_column(String(64), unique=True)
    MfaVerified: Mapped[bool] = mapped_column(Boolean, default=True)  # False = password ok, waiting for TOTP
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=lambda: utcnow())
    LastSeenAt: Mapped[datetime] = mapped_column(DateTime, default=lambda: utcnow())
    ExpiresAt: Mapped[datetime] = mapped_column(DateTime)  # absolute expiry
    RevokedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    UserAgent: Mapped[str] = mapped_column(String(200), default="")


class AuthToken(Base):
    """One-time tokens for password reset and team invitations (stored hashed, short-lived, single use)."""
    __tablename__ = "AuthToken"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    Purpose: Mapped[str] = mapped_column(String(20))  # password_reset | invite
    TokenHash: Mapped[str] = mapped_column(String(64), unique=True)
    UserId: Mapped[int | None] = mapped_column(ForeignKey("SmeUser.Id"), nullable=True)  # reset
    BusinessId: Mapped[int | None] = mapped_column(ForeignKey("SmeBusiness.Id"), nullable=True)  # invite
    Email: Mapped[str] = mapped_column(String(200), default="")
    Role: Mapped[str] = mapped_column(String(20), default="")
    CreatedBy: Mapped[int | None] = mapped_column(ForeignKey("SmeUser.Id"), nullable=True)
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=lambda: utcnow())
    ExpiresAt: Mapped[datetime] = mapped_column(DateTime)
    UsedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportBatch(Base):
    """One CSV/Excel upload: what was imported, skipped as duplicate, or rejected (with row errors)."""
    __tablename__ = "ImportBatch"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    BusinessId: Mapped[int] = mapped_column(ForeignKey("SmeBusiness.Id"), index=True)
    Kind: Mapped[str] = mapped_column(String(20))  # transactions | invoices | bills
    FileName: Mapped[str] = mapped_column(String(200))
    RowsTotal: Mapped[int] = mapped_column(Integer, default=0)
    RowsImported: Mapped[int] = mapped_column(Integer, default=0)
    RowsDuplicate: Mapped[int] = mapped_column(Integer, default=0)
    RowsRejected: Mapped[int] = mapped_column(Integer, default=0)
    ErrorsJson: Mapped[str] = mapped_column(Text, default="[]")
    CreatedBy: Mapped[int] = mapped_column(ForeignKey("SmeUser.Id"))
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=lambda: utcnow())


class AuditLog(Base):
    """Append-only, SHA-256 hash-chained audit trail (Hash = sha256(PrevHash + canonical record))."""
    __tablename__ = "AuditLog"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True)
    Ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    BusinessId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    Actor: Mapped[str] = mapped_column(String(200))
    ActorType: Mapped[str] = mapped_column(String(10))  # user | agent | system
    Action: Mapped[str] = mapped_column(String(100))
    Tool: Mapped[str] = mapped_column(String(100), default="")
    Tier: Mapped[str] = mapped_column(String(5), default="")
    ParamsHash: Mapped[str] = mapped_column(String(64), default="")
    ResultSummary: Mapped[str] = mapped_column(Text, default="")
    Decision: Mapped[str] = mapped_column(String(20), default="")
    PrevHash: Mapped[str] = mapped_column(String(64))
    Hash: Mapped[str] = mapped_column(String(64), unique=True)
