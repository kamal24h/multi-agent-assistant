# src/coordinator/app/supervisor/state.py

"""LangGraph state for the Supervisor subgraph (Phase 1).

Kept separate from `app.graphs.state.GraphState` so that:
  - Supervisor can evolve independently.
  - Routing modules can import it without circular imports.
  - SupervisorState is converted from/to GraphState in workflow.py.

Phase 1 scope: sequential single-task delegation.
"""
from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

from app.supervisor.task_contracts import AgentResult, AgentTask


class SupervisorState(TypedDict, total=False):
    # Input (converted from GraphState in workflow.supervisor_node)
    tenant_id: str
    user_id: str
    app_ids: list[str]
    authorization: str | None  # NEVER persisted; runtime only
    prompt: str
    terminology_context: str
    terminology_search_terms: list[str]
    intent: str
    confidence: float

    # Planning
    tasks: list[AgentTask]

    # Execution
    current_task_id: UUID | None
    results: list[AgentResult]

    # Finalization
    final_answer: str
    final_sources: list[dict[str, Any]]
    status: str  # "success" | "partial" | "failed"
    errors: list[dict[str, Any]]