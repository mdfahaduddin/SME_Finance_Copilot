"""Append-only, SHA-256 hash-chained audit log.

Each record stores PrevHash (the previous record's Hash) and
    Hash = sha256(canonical JSON of the record's fields + PrevHash)
so changing, deleting or reordering any row breaks every hash after it.
`verify_chain` recomputes the chain and reports the first broken record.

Parameters are stored only as a hash (ParamsHash) so the log never holds raw PII,
while still proving exactly which parameters were used.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog, utcnow

GENESIS = "0" * 64
AUDIT_LOCK_KEY = 7_340_211  # arbitrary constant identifying the audit-chain advisory lock


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def params_hash(params: Any) -> str:
    return hashlib.sha256(canonical_json(params).encode()).hexdigest() if params is not None else ""


def _record_hash(row: AuditLog) -> str:
    payload = {
        "Ts": row.Ts.isoformat(timespec="microseconds"),
        "BusinessId": row.BusinessId,
        "Actor": row.Actor,
        "ActorType": row.ActorType,
        "Action": row.Action,
        "Tool": row.Tool,
        "Tier": row.Tier,
        "ParamsHash": row.ParamsHash,
        "ResultSummary": row.ResultSummary,
        "Decision": row.Decision,
        "PrevHash": row.PrevHash,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def record(
    session: Session,
    *,
    action: str,
    actor: str,
    actor_type: str,
    business_id: int | None = None,
    tool: str = "",
    tier: str = "",
    params: Any = None,
    result: str = "",
    decision: str = "",
    commit: bool = True,
) -> AuditLog:
    """Append one audit record. Call inside the same transaction as the action it records."""
    if session.get_bind().dialect.name == "postgresql":
        # Serialise appends across workers: without this, two concurrent requests could read the same
        # PrevHash and fork the chain. The lock is released when the transaction commits.
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
    prev = session.scalar(select(AuditLog.Hash).order_by(AuditLog.Id.desc()).limit(1)) or GENESIS
    row = AuditLog(
        Ts=utcnow(), BusinessId=business_id, Actor=actor, ActorType=actor_type, Action=action, Tool=tool,
        Tier=tier, ParamsHash=params_hash(params), ResultSummary=result[:1000], Decision=decision, PrevHash=prev,
    )
    row.Hash = _record_hash(row)
    session.add(row)
    if commit:
        session.commit()
    else:
        session.flush()
    return row


def verify_chain(session: Session) -> dict:
    prev = GENESIS
    count = 0
    for row in session.scalars(select(AuditLog).order_by(AuditLog.Id)):
        count += 1
        if row.PrevHash != prev:
            return {"valid": False, "records": count, "brokenAtId": row.Id, "reason": "PrevHash does not link"}
        if _record_hash(row) != row.Hash:
            return {"valid": False, "records": count, "brokenAtId": row.Id, "reason": "Record content altered"}
        prev = row.Hash
    return {"valid": True, "records": count, "brokenAtId": None, "headHash": prev,
            "verifiedAt": utcnow().isoformat(timespec="seconds") + "Z"}


def to_dict(row: AuditLog) -> dict:
    return {
        "id": row.Id, "ts": row.Ts.isoformat(timespec="seconds") + "Z", "actor": row.Actor,
        "actorType": row.ActorType, "action": row.Action, "tool": row.Tool, "tier": row.Tier,
        "paramsHash": row.ParamsHash, "result": row.ResultSummary, "decision": row.Decision,
        "prevHash": row.PrevHash, "hash": row.Hash,
    }
