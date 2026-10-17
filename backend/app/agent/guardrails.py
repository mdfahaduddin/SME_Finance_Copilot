"""Input and output guardrails around the LLM.

Input:  length limit, control-character stripping, prompt-injection heuristics (flag + audit).
Output: groundedness check - every figure in the answer should trace back to a tool result
        (or the user's own message). Untraceable figures are reported to the UI, so a
        hallucinated number is visible rather than silently trusted.
        Advisory answers about financing get a "not financial advice" disclaimer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.agent.tools import INJECTION_PATTERNS

MAX_INPUT_CHARS = 2000
DISCLAIMER = ("_Estimates from your recorded data, for decision support only. This is not regulated "
              "financial advice; confirm terms with the lender before committing._")
ADVISORY_TOOLS = {"match_financing", "request_loan_application"}

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
NUMBER = re.compile(r"(?<![\w-])(-?\$?-?\d[\d,]*(?:\.\d+)?)\s?(k|K|M|m|%)?(?![\w])")


class InputRejected(ValueError):
    pass


@dataclass
class InputCheck:
    text: str
    injection_suspected: bool


def check_input(text: str) -> InputCheck:
    text = CONTROL.sub("", text or "").strip()
    if not text:
        raise InputRejected("Message is empty")
    if len(text) > MAX_INPUT_CHARS:
        raise InputRejected(f"Message is too long (max {MAX_INPUT_CHARS} characters)")
    return InputCheck(text, bool(INJECTION_PATTERNS.search(text)))


def _numbers_in(obj, out: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for m in NUMBER.finditer(obj):
            v = _parse(m)
            if v is not None:
                out.add(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)


def _parse(m: re.Match) -> float | None:
    raw, suffix = m.group(1), (m.group(2) or "")
    try:
        v = float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        return None
    if suffix in ("k", "K"):
        v *= 1_000
    elif suffix in ("M", "m"):
        v *= 1_000_000
    return v


@dataclass
class Groundedness:
    checked: int = 0
    grounded: int = 0
    unverified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"checked": self.checked, "grounded": self.grounded, "unverified": self.unverified}


def _close(v: float, sources: set[float], rel: float = 0.006) -> bool:
    return any(abs(v - s) <= max(1.0, rel * abs(s)) for s in sources)


def check_groundedness(answer: str, tool_results: list, user_text: str = "") -> Groundedness:
    sources: set[float] = set()
    _numbers_in(tool_results, sources)
    _numbers_in(user_text, sources)
    abs_sources = {abs(s) for s in sources}
    g = Groundedness()
    for m in NUMBER.finditer(answer):
        raw, suffix = m.group(1), m.group(2) or ""
        v = _parse(m)
        if v is None:
            continue
        is_money = "$" in raw or suffix in ("k", "K", "M", "m")
        is_pct = suffix == "%"
        if not (is_money or is_pct) and (abs(v) < 100 or 1990 <= v <= 2100):
            continue  # small counts, week numbers, years: not financial figures
        g.checked += 1
        ok = _close(abs(v), abs_sources) or (is_pct and (_close(v / 100, sources, 0.01) or _close(v, sources, 0.01)))
        if is_pct and not ok:
            ok = any(abs(v / 100 - s) <= 0.0006 for s in sources)
        if ok:
            g.grounded += 1
        else:
            g.unverified.append(m.group(0).strip())
    return g


def needs_disclaimer(tools_used: set[str], answer: str) -> bool:
    return bool(tools_used & ADVISORY_TOOLS) and "financial advice" not in answer.lower()


def compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)
