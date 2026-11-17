# src/coordinator/app/agents/inventory/runner.py

"""Thin wrapper used by workflow.py to run the Supervisor from GraphState."""
from __future__ import annotations

import logging
from typing import Any

from app.graphs.state import GraphState
from app.supervisor.graph import build_supervisor_graph

logger = logging.getLogger(__name__)

_SUPERVISOR = None


def _get_supervisor():
    global _SUPERVISOR
    if _SUPERVISOR is None:
        _SUPERVISOR = build_supervisor_graph()
    return _SUPERVISOR


async def run_supervisor(state: GraphState) -> dict[str, Any]:
    """Convert GraphState → SupervisorState, run, and return the final slice."""
    request = state["request"]
    decision = state.get("intent_decision")

    supervisor_input: dict[str, Any] = {
        "tenant_id": request.tenantId,
        "user_id": request.userId,
        "app_ids": list(request.appIds),
        "authorization": state.get("authorization"),
        "prompt": request.prompt,
        "terminology_context": state.get("terminology_context", ""),
        "terminology_search_terms": state.get("terminology_search_terms", []),
        "intent": decision.intent if decision else "",
        "confidence": decision.confidence if decision else 0.0,
    }

    result = await _get_supervisor().ainvoke(supervisor_input)
    return {
        "answer": result.get("final_answer", ""),
        "sources": result.get("final_sources", []),
        "status": result.get("status", "failed"),
    }