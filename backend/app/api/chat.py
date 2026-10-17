"""Copilot chat: sessions, history and the streaming agent endpoint (Server-Sent Events)."""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app import audit, models
from app.models import utcnow
from app.agent.orchestrator import Agent
from app.api.deps import CamelModel
from app.auth import CurrentUser, any_user
from app.db import get_db
from app.ratelimit import chat_limiter

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MessageBody(CamelModel):
    content: str = Field(min_length=1, max_length=4000)


class UpdateBody(CamelModel):
    """Rename and/or pin a conversation; fields left out are unchanged."""
    title: str | None = Field(None, max_length=200)
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = " ".join(v.split())  # one line, no stray spaces
        if not v:
            raise ValueError("Title cannot be empty")
        return v

    @model_validator(mode="after")
    def _something(self) -> "UpdateBody":
        if self.title is None and self.pinned is None:
            raise ValueError("Send a title or pinned")
        return self


def _own_session(db: Session, user: CurrentUser, session_id: int) -> models.ChatSession:
    s = db.get(models.ChatSession, session_id)
    # Conversations are private to the user who started them.
    if s is None or s.UserId != user.id or s.BusinessId != user.business_id:
        raise HTTPException(404, "Conversation not found")
    return s


def _session_dict(s: models.ChatSession, last: datetime | None = None, snippet: str | None = None) -> dict:
    d = {"id": s.Id, "title": s.Title, "createdAt": _iso(s.CreatedAt), "lastMessageAt": _iso(last or s.CreatedAt),
         "pinned": s.PinnedAt is not None}
    if snippet is not None:
        d["snippet"] = snippet
    return d


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds") + "Z"


def _like(term: str) -> str:
    """`%term%`, with LIKE wildcards in the user's text matched literally."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


_MARKDOWN = re.compile(r"\*\*|__|`|^\s*(?:#+|>|[-*]|\d+\.)\s+", re.M)


def _snippet(text: str, term: str, width: int = 100) -> str:
    """A one-line plain-text excerpt of `text` around the first match of `term` (markdown marks removed)."""
    text = _MARKDOWN.sub("", text)
    i = text.lower().find(term.lower())
    if i < 0:
        return ""
    start = max(0, i - width // 3)
    end = min(len(text), start + width)
    return ("…" if start else "") + " ".join(text[start:end].split()) + ("…" if end < len(text) else "")


@router.post("/sessions", status_code=201)
def create_session(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    s = models.ChatSession(BusinessId=user.business_id, UserId=user.id)
    db.add(s)
    db.commit()
    return _session_dict(s)


@router.get("/sessions")
def list_sessions(
    q: str = Query("", max_length=100, description="Search conversation titles and messages"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
) -> list[dict]:
    """The user's conversations: pinned ones first (most recently pinned on top), then the most recently active.
    With `q`, only those whose title or messages match."""
    Msg, Chat = models.ChatMessage, models.ChatSession
    last = select(Msg.SessionId, func.max(Msg.CreatedAt).label("last")).group_by(Msg.SessionId).subquery()
    stmt = (select(Chat, last.c.last).outerjoin(last, last.c.SessionId == Chat.Id)
            .where(Chat.UserId == user.id, Chat.BusinessId == user.business_id))
    term = " ".join(q.split())
    if term:
        pattern = _like(term)
        in_messages = select(Msg.SessionId).where(Msg.Content.ilike(pattern, escape="\\"))
        stmt = stmt.where(or_(Chat.Title.ilike(pattern, escape="\\"), Chat.Id.in_(in_messages)))
    rows = db.execute(stmt.order_by(Chat.PinnedAt.is_(None), Chat.PinnedAt.desc(),
                                    func.coalesce(last.c.last, Chat.CreatedAt).desc(), Chat.Id.desc()).limit(50)).all()
    if not term:
        return [_session_dict(s, t) for s, t in rows]

    # Show where the match is: the first matching message of each conversation.
    first: dict[int, str] = {}
    matches = db.execute(select(Msg.SessionId, Msg.Content)
                         .where(Msg.SessionId.in_([s.Id for s, _ in rows]), Msg.Content.ilike(pattern, escape="\\"))
                         .order_by(Msg.Id))
    for sid, content in matches:
        first.setdefault(sid, _snippet(content, term))
    return [_session_dict(s, t, first.get(s.Id, "")) for s, t in rows]


@router.patch("/sessions/{session_id}")
def update_session(session_id: int, body: UpdateBody, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(any_user)) -> dict:
    """Rename and/or pin one of the user's conversations. A renamed conversation keeps its title (no auto-title)."""
    s = _own_session(db, user, session_id)
    if body.title is not None:
        s.Title = body.title
    if body.pinned is not None and body.pinned != (s.PinnedAt is not None):
        s.PinnedAt = utcnow() if body.pinned else None
    db.commit()
    return _session_dict(s, db.scalar(select(func.max(models.ChatMessage.CreatedAt))
                                      .where(models.ChatMessage.SessionId == s.Id)))


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    """Delete one of the user's conversations and its messages.

    Approval requests the copilot created and the audit log are kept: they are records of what happened,
    not part of the conversation.
    """
    s = _own_session(db, user, session_id)
    count = db.execute(delete(models.ChatMessage).where(models.ChatMessage.SessionId == s.Id)).rowcount
    db.delete(s)
    audit.record(db, action="chat.deleted", actor=user.label, actor_type="user", business_id=user.business_id,
                 result=f"Conversation #{session_id} ({count} messages)", commit=False)
    db.commit()
    return {"deleted": session_id}


@router.get("/sessions/{session_id}/messages")
def history(session_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> list[dict]:
    _own_session(db, user, session_id)
    rows = db.scalars(select(models.ChatMessage).where(models.ChatMessage.SessionId == session_id)
                      .order_by(models.ChatMessage.Id))
    return [{"id": m.Id, "role": m.Role, "content": m.Content, "toolTrace": json.loads(m.ToolTraceJson or "[]"),
             **json.loads(m.MetaJson or "{}"), "createdAt": m.CreatedAt.isoformat(timespec="seconds") + "Z"}
            for m in rows]


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: int,
    body: MessageBody,
    stream: bool = Query(True, description="Stream Server-Sent Events; false returns the final JSON only"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
):
    _own_session(db, user, session_id)
    chat_limiter.check(f"chat|{user.id}")
    # The request-scoped session closes when the handler returns, so the streaming generator
    # opens its own session on the same engine.
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    if not stream:
        with factory() as s:
            events = list(Agent(s, user, session_id).run(body.content))
        final = next((e for e in events if e["type"] == "final"), None)
        if final is None:
            err = next((e for e in events if e["type"] == "error"), {"message": "No answer"})
            raise HTTPException(400, err["message"])
        return final

    def sse():
        with factory() as s:
            try:
                for event in Agent(s, user, session_id).run(body.content):
                    yield f"data: {json.dumps(event, default=str)}\n\n"
            except Exception:  # never leak internals to the client
                yield f"data: {json.dumps({'type': 'error', 'message': 'The copilot hit an internal error.'})}\n\n"
                raise
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
