"""Approval queue (human-in-the-loop) and audit log endpoints."""
from __future__ import annotations

import csv
import json
import io
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import actions, audit, models
from app.api.deps import CamelModel
from app.auth import CurrentUser, any_user, staff
from app.db import get_db
from app.ratelimit import action_limiter

router = APIRouter(prefix="/api", tags=["governance"])


class ActionRequestBody(CamelModel):
    tool: str = Field(max_length=100)
    params: dict[str, Any]
    rationale: str = Field("", max_length=2000)


class DecisionBody(CamelModel):
    password: str | None = Field(None, max_length=200)
    reason: str = Field("", max_length=1000)


@router.get("/approvals")
def list_approvals(
    status: Literal["pending", "approved", "rejected", "executed", "expired", "failed", "all"] = "all",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
) -> list[dict]:
    actions.expire_stale(db, user.business_id)
    q = select(models.AgentActionRequest).where(models.AgentActionRequest.BusinessId == user.business_id)
    if status != "all":
        q = q.where(models.AgentActionRequest.Status == status)
    return [actions.to_dict(r) for r in db.scalars(q.order_by(models.AgentActionRequest.Id.desc()))]


@router.get("/approvals/{request_id:int}")
def get_approval(request_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    actions.expire_stale(db, user.business_id)
    req = db.get(models.AgentActionRequest, request_id)
    if req is None or req.BusinessId != user.business_id:
        raise HTTPException(404, "Request not found")
    return actions.to_dict(req)


@router.get("/approvals/actions")
def available_actions(_: CurrentUser = Depends(any_user)) -> list[dict]:
    return [{"tool": s.name, "description": s.description, "approverRoles": list(s.approver_roles),
             "params": s.schema.model_json_schema()} for s in actions.ACTIONS.values()]


@router.post("/approvals", status_code=201)
def create_request(body: ActionRequestBody, db: Session = Depends(get_db), user: CurrentUser = Depends(staff)) -> dict:
    action_limiter.check(f"request|{user.id}")
    return actions.to_dict(actions.request_action(db, user, body.tool, body.params, via="ui",
                                                  rationale=body.rationale))


@router.post("/approvals/{request_id}/approve")
def approve(request_id: int, body: DecisionBody, db: Session = Depends(get_db),
            user: CurrentUser = Depends(staff)) -> dict:
    action_limiter.check(f"decide|{user.id}")
    return actions.to_dict(actions.approve(db, user, request_id, body.password, body.reason))


@router.post("/approvals/{request_id}/reject")
def reject(request_id: int, body: DecisionBody, db: Session = Depends(get_db),
           user: CurrentUser = Depends(staff)) -> dict:
    action_limiter.check(f"decide|{user.id}")
    return actions.to_dict(actions.reject(db, user, request_id, body.reason))


@router.get("/policy")
def policy(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    """The safety limits actually enforced by the server (shown on the Settings page), in the business currency."""
    from app.agent.orchestrator import MAX_ACTIONS_PER_TURN, MAX_STEPS
    from app.agent.tools import ROLE_TIERS, TOOLS
    from app.config import get_settings

    s = get_settings()
    lim = actions.business_limits(db, user.business_id)
    return {
        "currency": lim.currency,
        "reauthThreshold": lim.reauth,
        "schedulePaymentMax": lim.payment_max,
        "schedulePaymentDailyMax": lim.daily_max,
        "requestTtlHours": actions.REQUEST_TTL.total_seconds() / 3600,
        "safetyBufferWeeks": s.safety_buffer_weeks,
        "sessionMinutes": s.session_idle_minutes,
        "sessionAbsoluteHours": s.session_absolute_hours,
        "agent": {"maxStepsPerTurn": MAX_STEPS, "maxActionsPerTurn": MAX_ACTIONS_PER_TURN,
                  "mode": "online" if s.llm_enabled else "offline", "model": s.openai_model if s.llm_enabled else None},
        "roleTiers": {role: sorted(tiers) for role, tiers in ROLE_TIERS.items()},
        "approverRoles": {name: list(spec.approver_roles) for name, spec in actions.ACTIONS.items()},
        "tools": [{"name": t.name, "tier": t.tier} for t in TOOLS.values()],
    }


# ---------------------------------------------------------------- audit

def _audit_rows(db: Session, user: CurrentUser, actor_type: str | None, limit: int, offset: int):
    q = select(models.AuditLog).where(models.AuditLog.BusinessId == user.business_id)
    if actor_type:
        q = q.where(models.AuditLog.ActorType == actor_type)
    return db.scalars(q.order_by(models.AuditLog.Id.desc()).limit(limit).offset(offset)).all()


@router.get("/audit")
def audit_log(
    actor_type: Literal["user", "agent", "system"] | None = Query(None, alias="actorType"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(staff),
) -> dict:
    return {"items": [audit.to_dict(r) for r in _audit_rows(db, user, actor_type, limit, offset)],
            "limit": limit, "offset": offset}


@router.get("/audit/verify")
def audit_verify(db: Session = Depends(get_db), _: CurrentUser = Depends(staff)) -> dict:
    return audit.verify_chain(db)


@router.get("/audit/export")
def audit_export(
    format: Literal["json", "csv"] = "json",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(staff),
) -> Response:
    rows = [audit.to_dict(r) for r in reversed(_audit_rows(db, user, None, 100_000, 0))]
    audit.record(db, action="audit.exported", actor=user.label, actor_type="user", business_id=user.business_id,
                 result=f"{len(rows)} records as {format}")
    if format == "json":
        body = json.dumps({"chain": audit.verify_chain(db), "records": rows}, indent=2)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=audit-log.json"})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["id"])
    writer.writeheader()
    writer.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=audit-log.csv"})
