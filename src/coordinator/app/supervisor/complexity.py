# src/coordinator/app/supervisor/complexity.py — فاز ۱

"""Conservative complexity gate for Phase 1 (D9 revised).

Entry criteria for Supervisor (ALL must hold):
  1. intent is exactly ERP_DATA_QUERY (MIXED_QUERY stays on `planning`).
  2. decision.needs_clarification is False.
  3. decision.entities has at least 2 entries.
  4. prompt length >= 60 chars.
  5. At least one explicit complexity indicator is present.

Why so restrictive:
  - Spec §4.2: simple requests must not go through Supervisor.
  - Spec §13: "Multi-Agent only when complexity justifies it."
  - The existing `planning` route already handles MIXED_QUERY well;
    moving it to Supervisor in Phase 1 would be a regression risk.
"""
from __future__ import annotations

from typing import Any

from app.graphs.state import GraphState

_COMPLEXITY_INDICATORS: tuple[str, ...] = (
    "و همچنین",
    "همچنین",
    "مقایسه",
    "به علاوه",
    "در کنار",
    "به تفکیک",
    "با هم",
    "هم ... هم",
)


def is_complex_request(state: GraphState) -> bool:
    """Return True only if the request clearly warrants Supervisor.

    Never raises; returns False on any ambiguity (safe default).
    """
    decision = state.get("intent_decision")
    if decision is None:
        return False

    if decision.intent != "ERP_DATA_QUERY":
        return False
    if decision.needs_clarification:
        return False

    entities: dict[str, Any] = decision.entities or {}
    if len(entities) < 2:
        return False

    request = state.get("request")
    if request is None:
        return False
    prompt = request.prompt or ""
    if len(prompt) < 60:
        return False

    lowered = prompt.casefold()
    return any(k in lowered for k in _COMPLEXITY_INDICATORS)