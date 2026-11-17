# src/coordinator/app/supervisor/graph.py

"""Supervisor LangGraph (Phase 1) — sequential single-task delegation.

Per spec §7 and §13 Phase 1:
  - Plan: exactly one AgentTask for Inventory (no LLM planning in Phase 1;
    the task is derived deterministically from the request).
  - Execute: delegate to InventoryAgent with bounded resources.
  - Validate: deterministic checks only (no semantic verification).
  - Finalize: synthesize answer from AgentResult without extra LLM call.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.inventory.agent import run_inventory_agent
from app.supervisor.policies import (
    MAX_TOOL_CALLS_PER_TASK,
    TASK_TIMEOUT_SECONDS,
)
from app.supervisor.state import SupervisorState
from app.supervisor.task_contracts import (
    AgentResult,
    AgentTask,
    AgentType,
    TaskStatus,
)

logger = logging.getLogger(__name__)


def _build_inventory_task(state: SupervisorState) -> AgentTask:
    """Derive the single Inventory task deterministically.

    Phase 1 deliberately avoids LLM-based planning. If the user prompt is
    too complex to fit one objective, the complexity gate should have
    rejected it upstream. This keeps Phase 1 auditable and cheap.
    """
    prompt = state["prompt"]
    input_context = {
        "objective": prompt,
        "original_prompt": prompt,
        "terminology_context": state.get("terminology_context", ""),
        "terminology_search_terms": state.get("terminology_search_terms", []),
        "app_ids": state.get("app_ids", []),
    }
    return AgentTask(
        task_id=uuid4(),
        agent_type=AgentType.INVENTORY,
        objective=prompt,
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        input_context=input_context,
        expected_output_schema="inventory_result_v1",
        dependencies=[],
        max_tool_calls=MAX_TOOL_CALLS_PER_TASK,
        timeout_seconds=TASK_TIMEOUT_SECONDS,
    )


def _validate_result(task: AgentTask, result: AgentResult) -> list[dict[str, Any]]:
    """Deterministic validation (spec §5.7.a).

    Returns a list of validation errors (empty if valid).
    """
    errors: list[dict[str, Any]] = []

    if result.task_id != task.task_id:
        errors.append({"code": "validation_task_id_mismatch"})
    if result.tenant_id != task.tenant_id:
        errors.append({"code": "validation_tenant_mismatch"})
    if result.user_id != task.user_id:
        errors.append({"code": "validation_user_mismatch"})
    if result.status == TaskStatus.SUCCESS and not result.evidence:
        errors.append({"code": "validation_missing_evidence"})
    if result.status == TaskStatus.SUCCESS and not result.result.get("answer"):
        errors.append({"code": "validation_missing_answer"})
    if int(result.execution_metrics.get("tool_calls", 0)) > task.max_tool_calls:
        errors.append({"code": "validation_tool_calls_exceeded"})

    return errors


def _synthesize(result: AgentResult, validation_errors: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], str]:
    """Build the final answer with NO extra LLM call (Phase 1, D5)."""
    if validation_errors:
        return (
            "پاسخ از Agent موجودی دریافت شد ولی اعتبارسنجی آن ناموفق بود. "
            "لطفاً درخواست را دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            [],
            "failed",
        )

    if result.status == TaskStatus.SUCCESS:
        answer = str(result.result.get("answer", "")).strip()
        sources = [
            {
                "type": "erp_mcp",
                "tool": ev.tool_name,
                "row_count": ev.row_count,
                "preview": ev.structured_preview,
            }
            for ev in result.evidence
        ]
        return (answer or "پاسخی از Agent موجودی دریافت نشد.", sources, "success")

    if result.status == TaskStatus.PARTIAL:
        answer = str(result.result.get("answer", "")).strip()
        return (
            (answer + "\n\n(توجه: این پاسخ ناقص است.)") if answer
            else "نتیجه ناقص از Agent موجودی دریافت شد.",
            [{"type": "erp_mcp", "tool": ev.tool_name} for ev in result.evidence],
            "partial",
        )

    # FAILED
    codes = ", ".join(str(e.get("code", "unknown")) for e in result.errors) or "unknown"
    return (
        f"پاسخ‌دهی از طریق Supervisor ناموفق بود (کد: {codes}). "
        "لطفاً دوباره تلاش کنید یا درخواست را ساده‌تر بیان کنید.",
        [],
        "failed",
    )


def build_supervisor_graph():
    graph: StateGraph = StateGraph(SupervisorState)

    async def plan_node(state: SupervisorState) -> dict[str, Any]:
        task = _build_inventory_task(state)
        return {"tasks": [task], "current_task_id": task.task_id}

    async def execute_node(state: SupervisorState) -> dict[str, Any]:
        tasks = state.get("tasks") or []
        if not tasks:
            return {"results": [], "errors": [{"code": "no_tasks"}]}
        task = tasks[0]
        result = await run_inventory_agent(task, authorization=state.get("authorization"))
        return {"results": [result]}

    async def validate_node(state: SupervisorState) -> dict[str, Any]:
        tasks = state.get("tasks") or []
        results = state.get("results") or []
        if not tasks or not results:
            return {"errors": [{"code": "missing_task_or_result"}]}
        errors = _validate_result(tasks[0], results[0])
        return {"errors": errors}

    async def finalize_node(state: SupervisorState) -> dict[str, Any]:
        results = state.get("results") or []
        if not results:
            return {
                "final_answer": "پاسخ‌دهی ناموفق بود.",
                "final_sources": [],
                "status": "failed",
            }
        answer, sources, status = _synthesize(results[0], state.get("errors") or [])
        return {
            "final_answer": answer,
            "final_sources": sources,
            "status": status,
        }

    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "validate")
    graph.add_edge("validate", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()