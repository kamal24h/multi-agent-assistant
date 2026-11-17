# src/coordinator/app/agents/inventory/agent.py

"""Inventory Agent — Phase 1 implementation.

Behavior-preserving extraction from workflow.local_mcp_node, wrapped in
the AgentTask / AgentResult contract. It uses the same MCP client, the same
LLM policy stage (`erp_summarizer`), the same guardrails, and the same
tool selection logic.

Invariants:
  - Uses ONLY `list_read_only_tools` / `call_tool`. Never `*_write_*`.
  - Enforces `max_tool_calls` and `timeout_seconds` from the task.
  - Never persists or logs authorization context.
  - Never calls more than 1 business tool in Phase 1 (retry allowed once).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.agents.inventory.prompts import (
    SUMMARIZER_SYSTEM_PROMPT,
    TOOL_SELECTOR_SYSTEM_PROMPT,
)
from app.agents.inventory.schemas import InventoryResult
from app.core.config import settings
from app.core.guardrails import guard_output, sanitize_tool_payload
from app.routing.llm_factory import build_local_llm
from app.services.llm_router import answer_external_first
from app.services.mcp_client import ErpMcpClient, McpClientError
from app.supervisor.task_contracts import (
    AgentResult,
    AgentTask,
    AgentType,
    EvidenceItem,
    TaskStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# Tool selection (mirrors workflow.select_erp_tool)
# ---------------------------------------------------------

def _extract_json_object(raw: str) -> dict[str, Any]:
    """Robust JSON extraction from LLM output (mirrors workflow._extract_json)."""
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        candidate = json.loads(raw[start : i + 1])
                        if isinstance(candidate, dict):
                            return candidate
                    except json.JSONDecodeError:
                        pass
                    return {}
    return {}


async def _select_tool(
    question: str,
    tools: list[dict[str, Any]],
    *,
    terminology_context: str = "",
) -> dict[str, Any]:
    compact_tools = [
        {
            "name": t.get("name"),
            "description": str(t.get("description", ""))[:500],
            "inputSchema": t.get("inputSchema", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", TOOL_SELECTOR_SYSTEM_PROMPT),
            (
                "human",
                "سؤال: {question}\n"
                "اصطلاحات سازمانی (راهنما): {terminology_context}\n"
                "ابزارهای مجاز (JSON): {tools}\n"
                "فقط JSON:",
            ),
        ]
    )
    chain = prompt | build_local_llm(temperature=0.0, num_predict=256) | StrOutputParser()
    raw = (
        await chain.ainvoke(
            {
                "question": question,
                "terminology_context": terminology_context or "(بدون اصطلاح مرتبط)",
                "tools": json.dumps(compact_tools, ensure_ascii=False),
            }
        )
    ).strip()
    parsed = _extract_json_object(raw)
    allowed = {t["name"] for t in tools}
    name = parsed.get("name")
    args = parsed.get("arguments", {})
    if name not in allowed or not isinstance(args, dict):
        raise McpClientError("no_matching_erp_tool")
    return {"name": name, "arguments": args}


# ---------------------------------------------------------
# Summarization (mirrors workflow.summarize_erp_result)
# ---------------------------------------------------------

async def _summarize(
    question: str,
    tool_name: str,
    result: dict[str, Any],
    *,
    terminology_context: str = "",
) -> str:
    prompt = (
        f"پرسش کاربر: {question}\n"
        f"اصطلاحات سازمانی (راهنما، نه منبع داده): {terminology_context or '(بدون مورد)'}\n"
        f"نام ابزار: {tool_name}\n"
        f"نتیجه ERP (JSON): {json.dumps(result, ensure_ascii=False, default=str)[:12000]}\n"
        f"پاسخ:"
    )
    answer, _source = await answer_external_first(
        "erp_summarizer", prompt, system_prompt=SUMMARIZER_SYSTEM_PROMPT,
    )
    return answer


# ---------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------

def _hash_arguments(arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _preview_structured(structured: Any, limit: int = 500) -> str:
    try:
        encoded = json.dumps(structured, ensure_ascii=False, default=str)
    except Exception:
        encoded = str(structured)
    return encoded[:limit]


def _count_rows(structured: Any) -> int | None:
    if isinstance(structured, list):
        return len(structured)
    if isinstance(structured, dict):
        for key in ("items", "rows", "results", "data"):
            value = structured.get(key)
            if isinstance(value, list):
                return len(value)
    return None


# ---------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------

async def run_inventory_agent(
    task: AgentTask,
    *,
    authorization: str | None,
) -> AgentResult:
    """Execute an Inventory Agent task and return a structured AgentResult.

    `authorization` is passed separately (never stored in the task).
    """
    if task.agent_type != AgentType.INVENTORY:
        return AgentResult(
            task_id=task.task_id,
            agent_type=task.agent_type,
            tenant_id=task.tenant_id,
            user_id=task.user_id,
            status=TaskStatus.FAILED,
            errors=[{"code": "unsupported_agent_type"}],
        )

    started = time.perf_counter()
    errors: list[dict[str, Any]] = []
    evidence: list[EvidenceItem] = []
    business_tool_calls = 0
    tool_name: str | None = None

    client = ErpMcpClient(authorization=authorization)

    try:
        # Wrap in timeout (hard cap from task contract).
        async def _work() -> dict[str, Any]:
            nonlocal business_tool_calls, tool_name

            tools = await client.list_read_only_tools(task.tenant_id, task.user_id)
            if not tools:
                raise McpClientError("no_read_only_erp_tools_available")

            terminology_context = str(task.input_context.get("terminology_context", ""))
            selected = await _select_tool(
                task.objective, tools, terminology_context=terminology_context,
            )
            tool_name = selected["name"]

            business_tool_calls += 1
            if business_tool_calls > task.max_tool_calls:
                raise McpClientError("max_tool_calls_exceeded")

            result = await client.call_tool(
                selected["name"],
                selected["arguments"],
                task.tenant_id,
                task.user_id,
            )

            if settings.guardrails_enabled:
                result = sanitize_tool_payload(
                    result, max_chars=settings.guardrails_max_tool_result_chars,
                )

            evidence.append(
                EvidenceItem(
                    source_type="erp_mcp",
                    tool_name=selected["name"],
                    arguments_hash=_hash_arguments(selected["arguments"]),
                    row_count=_count_rows(result.get("structuredContent")),
                    structured_preview=_preview_structured(
                        result.get("structuredContent"),
                    ),
                    called_at=datetime.now(timezone.utc).isoformat(),
                )
            )

            answer = await _summarize(
                task.objective,
                selected["name"],
                result,
                terminology_context=terminology_context,
            )
            if settings.guardrails_enabled:
                answer, _flags = guard_output(answer, settings.guardrails_max_output_chars)

            return {
                "answer": answer,
                "tool_name": selected["name"],
                "row_count": evidence[-1].row_count or 0,
                "structured": result.get("structuredContent"),
            }

        raw = await asyncio.wait_for(_work(), timeout=float(task.timeout_seconds))

        # Validate structured result shape.
        structured = InventoryResult(
            answer=raw["answer"],
            rows=[],  # extraction of rows from structured is out-of-scope in Phase 1
            tool_name=raw.get("tool_name"),
            row_count=int(raw.get("row_count") or 0),
        )

        status = TaskStatus.SUCCESS
        result_payload = structured.model_dump()

    except asyncio.TimeoutError:
        errors.append({"code": "task_timeout", "timeout_seconds": task.timeout_seconds})
        status = TaskStatus.FAILED
        result_payload = {}
    except McpClientError as exc:
        errors.append({"code": exc.code})
        status = TaskStatus.FAILED
        result_payload = {}
    except Exception as exc:
        logger.exception("Inventory Agent unexpected failure")
        errors.append({"code": "agent_unexpected_error", "detail": type(exc).__name__})
        status = TaskStatus.FAILED
        result_payload = {}

    duration = time.perf_counter() - started
    return AgentResult(
        task_id=task.task_id,
        agent_type=task.agent_type,
        tenant_id=task.tenant_id,
        user_id=task.user_id,
        status=status,
        result=result_payload,
        evidence=evidence,
        errors=errors,
        execution_metrics={
            "duration_seconds": round(duration, 3),
            "tool_calls": business_tool_calls,
            "tool_name": tool_name,
        },
    )