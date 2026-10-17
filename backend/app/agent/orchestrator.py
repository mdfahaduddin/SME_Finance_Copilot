"""Agent orchestrator: the tool-calling loop.

One user turn:
  1. Input guardrails (length, control chars, injection heuristics -> audit flag).
  2. Build masked conversation: system prompt + recent history + user message, PII replaced by tokens.
  3. Loop (max MAX_STEPS): call the LLM with the tools allowed for the user's role.
       - For each tool call: policy gate (tool exists, tier allowed for role, per-turn action cap),
         execute, audit, feed the masked JSON result back to the model.
       - T2 tools only create pending approval requests.
  4. Final answer: unmask, groundedness check, disclaimer when advisory, persist, audit.
If no LLM is configured or the provider fails, the offline rule-based router answers instead,
using the same tool executor (so policy and audit still apply).

Yields UI events (dicts) so the API can stream them as Server-Sent Events.
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, fx, models
from app.actions import ActionError
from app.agent import fallback, guardrails
from app.agent.llm import LLMError, get_llm
from app.agent.pii import Masker
from app.agent.prompts import build_system_prompt
from app.agent.tools import TOOLS, ToolContext, tools_for
from app.auth import CurrentUser

MAX_STEPS = 8
MAX_ACTIONS_PER_TURN = 3
MAX_TOOL_RESULT_CHARS = 12_000
HISTORY_MESSAGES = 12


class StreamingUnmasker:
    """Unmask streamed text without splitting a placeholder like "[PERSON_1]" across chunks."""

    def __init__(self, masker: Masker):
        self.masker = masker
        self.buf = ""

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        cut = self.buf.rfind("[")
        if cut != -1 and "]" not in self.buf[cut:] and len(self.buf) - cut < 20:
            ready, self.buf = self.buf[:cut], self.buf[cut:]
        else:
            ready, self.buf = self.buf, ""
        return self.masker.unmask(ready)

    def flush(self) -> str:
        out, self.buf = self.masker.unmask(self.buf), ""
        return out


def _summarize(name: str, result: dict) -> str:
    """Short, PII-free line for the tool trace and audit log."""
    if "error" in result:
        return f"Error: {result['error']}"
    if result.get("status") == "awaiting_approval":
        return f"Approval request #{result['requestId']} created"
    s = result.get("summary")
    if name == "forecast_cashflow" and isinstance(s, dict):
        return f"Lowest {fx.fmt(s['lowestBalance'], result.get('currency', 'USD'))} in week {s['lowestWeek']}"
    if name == "analyze_financials" and "healthScore" in result:
        return f"Health score {result['healthScore']['score']:.0f}/100"
    if name == "match_financing" and "eligible" in result:
        top = result["eligible"][0] if result["eligible"] else None
        return f"{len(result['eligible'])} eligible" + (f"; top: {top['lender']} {top['name']}" if top else "")
    if name == "run_scenario" and "verdict" in result:
        return result["verdict"]
    if "count" in result:
        return f"{result['count']} records"
    return "OK"


class Agent:
    def __init__(self, db: Session, user: CurrentUser, session_id: int):
        self.db = db
        self.user = user
        self.session_id = session_id
        self.ctx = ToolContext(db=db, user=user)
        self.masker = Masker.for_business(db, user.business_id)
        self.allowed = {t.name for t in tools_for(user.role)}
        self.trace: list[dict] = []
        self.raw_results: list[Any] = []
        self.actions_this_turn = 0

    # ------------------------------------------------------------ tool execution (policy gate)

    def execute_tool(self, name: str, raw_args: str | dict, call_id: str) -> tuple[dict, dict]:
        tool = TOOLS.get(name)
        tier = tool.tier if tool else "?"
        started = time.perf_counter()
        decision = "allowed"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            args = json.loads(self.masker.unmask(json.dumps(args)))  # model may echo placeholders
        except (json.JSONDecodeError, ValueError) as e:
            args, result, decision = {}, {"error": f"Invalid arguments: {e}"}, "denied"
        else:
            if tool is None:
                result, decision = {"error": f"Unknown tool '{name}'. Use only the tools provided."}, "denied"
            elif name not in self.allowed:
                result, decision = {"error": f"Tool '{name}' is not permitted for role '{self.user.role}'."}, "denied"
            elif tier == "T2" and self.actions_this_turn >= MAX_ACTIONS_PER_TURN:
                result, decision = {"error": "Too many action requests in one turn. Ask the user first."}, "denied"
            else:
                try:
                    result = tool.handler(self.ctx, dict(args))
                    if tier == "T2":
                        self.actions_this_turn += 1
                        decision = "pending_approval"
                except ActionError as e:
                    result, decision = {"error": str(e)}, "refused"
                except (KeyError, ValueError, TypeError) as e:
                    result, decision = {"error": f"Could not run {name}: {e}"}, "error"

        summary = _summarize(name, result)
        entry = {"id": call_id, "name": name, "tier": tier, "args": args, "decision": decision, "summary": summary,
                 "ms": round((time.perf_counter() - started) * 1000)}
        if result.get("status") == "awaiting_approval":
            entry["approvalRequestId"] = result["requestId"]
        self.trace.append(entry)
        self.raw_results.append(result)
        # T2 requests write their own audit records (action.requested); log everything else here.
        if tier != "T2" or decision != "pending_approval":
            audit.record(self.db, action="agent.tool_call", actor=f"agent for {self.user.label}", actor_type="agent",
                         business_id=self.user.business_id, tool=name, tier=tier, params=args,
                         result=summary, decision=decision)
        return result, entry

    # ------------------------------------------------------------ conversation

    def _history(self) -> list[dict]:
        rows = self.db.scalars(select(models.ChatMessage).where(models.ChatMessage.SessionId == self.session_id)
                               .order_by(models.ChatMessage.Id.desc()).limit(HISTORY_MESSAGES)).all()
        return [{"role": r.Role, "content": self.masker.mask(r.Content)} for r in reversed(rows)]

    def _save(self, role: str, content: str, trace: list | None = None, meta: dict | None = None) -> models.ChatMessage:
        msg = models.ChatMessage(SessionId=self.session_id, Role=role, Content=content,
                                 ToolTraceJson=json.dumps(trace or []), MetaJson=json.dumps(meta or {}))
        self.db.add(msg)
        session = self.db.get(models.ChatSession, self.session_id)
        if role == "user" and session.Title == "New conversation":
            session.Title = content[:60]
        self.db.commit()
        return msg

    def run(self, text: str) -> Iterator[dict]:
        try:
            check = guardrails.check_input(text)
        except guardrails.InputRejected as e:
            yield {"type": "error", "message": str(e)}
            return
        if check.injection_suspected:
            audit.record(self.db, action="agent.injection_suspected", actor=self.user.label, actor_type="user",
                         business_id=self.user.business_id, params=check.text, decision="flagged",
                         result="User message matched prompt-injection patterns")
        history = self._history()
        self._save("user", check.text)

        llm = get_llm()
        mode = "online"
        answer = ""
        if llm is not None:
            try:
                answer = yield from self._run_llm(llm, history, check.text)
            except LLMError as e:
                audit.record(self.db, action="agent.llm_error", actor="system", actor_type="system",
                             business_id=self.user.business_id, result=str(e)[:300], decision="fallback")
                yield {"type": "reset"}  # discard any partially streamed text
                yield {"type": "status", "text": "AI service unavailable - switching to offline mode"}
                self.trace.clear()
                self.raw_results.clear()
                llm = None
        if llm is None:
            mode = "offline"
            answer = yield from self._run_offline(check.text)

        tools_used = {t["name"] for t in self.trace}
        if guardrails.needs_disclaimer(tools_used, answer):
            answer = f"{answer}\n\n{guardrails.DISCLAIMER}"
            yield {"type": "delta", "text": f"\n\n{guardrails.DISCLAIMER}"}
        grounded = guardrails.check_groundedness(answer, self.raw_results, check.text)
        meta = {"mode": mode, "groundedness": grounded.to_dict(), "approvalRequests": list(self.ctx.approval_requests),
                "piiMasked": self.masker.masked_count}
        msg = self._save("assistant", answer, self.trace, meta)
        audit.record(self.db, action="agent.answer", actor=f"agent for {self.user.label}", actor_type="agent",
                     business_id=self.user.business_id, decision=mode,
                     result=f"{len(self.trace)} tool calls; {grounded.grounded}/{grounded.checked} figures grounded; "
                            f"{self.masker.masked_count} PII values masked")
        yield {"type": "final", "messageId": msg.Id, "content": answer, "toolTrace": self.trace, **meta}

    def _run_llm(self, llm, history: list[dict], text: str):
        biz = self.db.get(models.SmeBusiness, self.user.business_id)
        system = build_system_prompt(biz.Name, biz.Industry, biz.today.isoformat(), self.user.role, biz.Currency)
        messages: list[dict] = [{"role": "system", "content": system}, *history,
                                {"role": "user", "content": self.masker.mask(text)}]
        tool_schemas = [t.openai_schema() for t in tools_for(self.user.role)]
        yield {"type": "status", "text": "Thinking..."}
        for _ in range(MAX_STEPS):
            unmasker = StreamingUnmasker(self.masker)
            turn = None
            for kind, payload in llm.stream(messages, tool_schemas, user_ref=str(self.user.id)):
                if kind == "delta":
                    out = unmasker.feed(payload)
                    if out:
                        yield {"type": "delta", "text": out}
                else:
                    turn = payload
            tail = unmasker.flush()
            if tail:
                yield {"type": "delta", "text": tail}
            if turn is None:
                raise LLMError("empty response")
            if not turn.tool_calls:
                return self.masker.unmask(turn.content).strip()

            messages.append({"role": "assistant", "content": turn.content or None, "_raw": turn.raw, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in turn.tool_calls]})
            if turn.content:
                yield {"type": "delta", "text": "\n\n"}
            for call in turn.tool_calls:
                tool = TOOLS.get(call.name)
                yield {"type": "tool_call", "id": call.id, "name": call.name, "tier": tool.tier if tool else "?"}
                result, entry = self.execute_tool(call.name, call.arguments, call.id)
                yield {"type": "tool_result", **entry}
                if "approvalRequestId" in entry:
                    yield {"type": "approval", "requestId": entry["approvalRequestId"], "summary": result["summary"]}
                content = self.masker.mask(guardrails.compact(result))
                if len(content) > MAX_TOOL_RESULT_CHARS:
                    content = content[:MAX_TOOL_RESULT_CHARS] + '..."(truncated)"'
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        yield {"type": "status", "text": "Step limit reached"}
        return "I needed more steps than allowed to answer that. Could you narrow the question?"

    def _run_offline(self, text: str):
        intent, steps = fallback.plan(text, self.ctx)
        results: dict[str, dict] = {}
        for i, (name, args) in enumerate(steps):
            call_id = f"offline_{i}"
            yield {"type": "tool_call", "id": call_id, "name": name, "tier": TOOLS[name].tier}
            result, entry = self.execute_tool(name, args, call_id)
            yield {"type": "tool_result", **entry}
            if "approvalRequestId" in entry:
                yield {"type": "approval", "requestId": entry["approvalRequestId"], "summary": result["summary"]}
            results[name] = result
        answer = f"{fallback.compose(intent, results, self.ctx.ledger.business.Currency)}\n\n{fallback.OFFLINE_NOTE}"
        yield {"type": "delta", "text": answer}
        return answer
