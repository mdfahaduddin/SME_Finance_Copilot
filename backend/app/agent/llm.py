"""LLM client abstraction.

`OpenAIClient` streams the OpenAI Responses API with function calling. `ScriptedLLM` replays
canned turns for deterministic tests. Both yield the same events:
    ("delta", str)       - a chunk of assistant text
    ("turn", LLMTurn)    - the complete assistant turn (text + tool calls)
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from app.config import get_settings


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string as produced by the model


@dataclass
class LLMTurn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: list[dict] | None = None  # provider-specific output items to replay on the next step


class LLMClient(Protocol):
    name: str

    def stream(self, messages: list[dict], tools: list[dict], user_ref: str) -> Iterator[tuple[str, object]]: ...


class OpenAIClient:
    """OpenAI Responses API with function calling and streaming.

    The orchestrator speaks Chat-style messages; this client translates them to Responses
    input items. With store=False nothing is retained by the provider, so the model's
    encrypted reasoning items are passed back between tool-calling steps instead.
    """

    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float = 90.0):
        from openai import OpenAI  # imported lazily so offline mode never needs the SDK configured

        self.model = model
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=1)

    @staticmethod
    def _to_input(messages: list[dict]) -> tuple[str, list[dict]]:
        instructions, items = "", []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                instructions += msg["content"]
            elif role == "tool":
                items.append({"type": "function_call_output", "call_id": msg["tool_call_id"],
                              "output": msg["content"]})
            elif role == "assistant" and msg.get("_raw"):
                items.extend(msg["_raw"])  # reasoning + function_call items exactly as returned
            elif role == "assistant" and msg.get("tool_calls"):
                if msg.get("content"):
                    items.append({"role": "assistant", "content": msg["content"]})
                items.extend({"type": "function_call", "call_id": c["id"], "name": c["function"]["name"],
                              "arguments": c["function"]["arguments"]} for c in msg["tool_calls"])
            else:
                items.append({"role": role, "content": msg["content"] or ""})
        return instructions, items

    @staticmethod
    def _to_tools(tools: list[dict]) -> list[dict]:
        return [{"type": "function", "name": t["function"]["name"], "description": t["function"]["description"],
                 "parameters": t["function"]["parameters"], "strict": False} for t in tools]

    def stream(self, messages: list[dict], tools: list[dict], user_ref: str) -> Iterator[tuple[str, object]]:
        instructions, items = self._to_input(messages)
        try:
            stream = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=items,
                tools=self._to_tools(tools) if tools else None,
                stream=True,
                store=False,  # do not retain conversation data at the provider
                include=["reasoning.encrypted_content"],
                max_output_tokens=4000,
                # Pseudonymous id for provider abuse monitoring: a hash, never the email.
                safety_identifier=hashlib.sha256(user_ref.encode()).hexdigest()[:32],
            )
            response = None
            for event in stream:
                etype = getattr(event, "type", "")
                if etype == "response.output_text.delta":
                    yield "delta", event.delta
                elif etype == "response.completed":
                    response = event.response
                elif etype in ("response.failed", "error"):
                    detail = getattr(getattr(event, "response", None), "error", None) or getattr(event, "message", "")
                    raise LLMError(f"Provider reported failure: {detail}")
            if response is None:
                raise LLMError("Stream ended without a completed response")
            text, calls, raw = [], [], []
            for item in response.output:
                raw.append(item.model_dump(exclude_none=True))
                if item.type == "message":
                    text += [c.text for c in item.content if getattr(c, "type", "") == "output_text"]
                elif item.type == "function_call":
                    calls.append(ToolCall(item.call_id, item.name, item.arguments or "{}"))
            yield "turn", LLMTurn(content="".join(text), tool_calls=calls, raw=raw)
        except LLMError:
            raise
        except Exception as e:  # network, auth, model errors -> caller falls back to offline mode
            raise LLMError(f"{type(e).__name__}: {e}") from e


class ScriptedLLM:
    """Test double: each call returns the next scripted turn (or a turn computed from the messages)."""

    name = "scripted"

    def __init__(self, turns: list[LLMTurn | Callable[[list[dict]], LLMTurn]]):
        self.turns = list(turns)
        self.calls: list[list[dict]] = []
        self.tools_seen: list[list[str]] = []

    def stream(self, messages: list[dict], tools: list[dict], user_ref: str) -> Iterator[tuple[str, object]]:
        self.calls.append([dict(m) for m in messages])
        self.tools_seen.append([t["function"]["name"] for t in tools])
        if not self.turns:
            raise LLMError("script exhausted")
        turn = self.turns.pop(0)
        if callable(turn):
            turn = turn(messages)
        if turn.content:
            for word in turn.content.split(" "):
                yield "delta", word + " "
        yield "turn", LLMTurn(turn.content.strip(), turn.tool_calls)


_override: LLMClient | None = None
_force_offline = False


def set_llm_override(client: LLMClient | None) -> None:
    """Tests inject a ScriptedLLM here."""
    global _override
    _override = client


def force_offline(value: bool) -> None:
    """Tests run offline by default so they never call the provider or need a key."""
    global _force_offline
    _force_offline = value


def get_llm() -> LLMClient | None:
    if _override is not None:
        return _override
    if _force_offline:
        return None
    s = get_settings()
    if not s.llm_enabled:
        return None
    return OpenAIClient(s.openai_api_key, s.openai_model)
