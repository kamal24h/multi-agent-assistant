# src/coordinator/app/supervisor/task_contracts.py

"""Formal Task Contract between Supervisor and Domain Agents (Phase 1).

Per Multi-Agent Architecture Specification v1.0 §6:
  - AgentTask: identity, objective, bounded resources.
  - AgentResult: structured outcome with evidence and metrics.

Security invariants (§6.1, §9):
  - tenant_id / user_id MUST originate from server-side request context.
  - authorization_context is NEVER persisted or logged; it is injected
    at runtime from GraphState.authorization.
  - The LLM and the Agent MUST NOT alter or elevate these values.
  - Every sensitive tool call must forward the validated context to MCP.

Evidence (§6.2, D4 decision):
  - We do NOT include full tool payloads in evidence.
  - We include `arguments_hash` and `structured_preview` (truncated).
  - This protects against log leakage and reduces AgentResult size.
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentType(str, Enum):
    """Supported agent types in Phase 1."""

    INVENTORY = "inventory"


class TaskStatus(str, Enum):
    """Terminal status of a delegated task."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class EvidenceItem(BaseModel):
    """Traceable evidence for a single tool call.

    Notes:
      - `arguments_hash` is sha256 of canonical JSON of arguments.
        Raw arguments are NOT persisted here (may contain identifiers).
      - `structured_preview` is a bounded preview of structuredContent.
        It is enough for a human reviewer to spot-check the result,
        but not a full payload.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=40)  # e.g. "erp_mcp"
    tool_name: str = Field(min_length=1, max_length=200)
    arguments_hash: str = Field(min_length=16, max_length=128)
    row_count: int | None = Field(default=None, ge=0)
    structured_preview: str = Field(default="", max_length=600)
    called_at: str = Field(min_length=10, max_length=40)  # ISO8601 UTC


class AgentTask(BaseModel):
    """Bounded, auditable task contract (spec §6.1).

    The `authorization_context` field is intentionally NOT part of this model.
    The Supervisor injects it at runtime into the Agent's execution context,
    so it never persists or appears in logs.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: UUID = Field(default_factory=uuid4)
    parent_task_id: UUID | None = None
    agent_type: AgentType
    objective: str = Field(min_length=1, max_length=2000)
    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=200)
    input_context: dict[str, Any] = Field(default_factory=dict)
    expected_output_schema: str = Field(default="inventory_result_v1", max_length=100)
    dependencies: list[UUID] = Field(default_factory=list)
    max_tool_calls: int = Field(default=2, ge=1, le=10)
    timeout_seconds: int = Field(default=90, ge=5, le=180)


class AgentResult(BaseModel):
    """Structured result returned by an Agent (spec §6.2)."""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    agent_type: AgentType
    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=200)
    status: TaskStatus
    result: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    execution_metrics: dict[str, Any] = Field(default_factory=dict)


# ---------- Sanitization helpers ----------

_SENSITIVE_KEYS_FOR_LOG = frozenset(
    {"authorization", "authorization_context", "bearer", "api_key", "token"}
)


def sanitize_task_for_log(task: AgentTask) -> dict[str, Any]:
    """Return a log-safe dict representation of an AgentTask.

    Never call `task.model_dump()` directly for logging — this helper removes
    any accidentally nested sensitive keys from `input_context`.
    """

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: ("[REDACTED]" if str(k).lower() in _SENSITIVE_KEYS_FOR_LOG else _walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_walk(v) for v in value[:50]]
        return value

    return {
        "task_id": str(task.task_id),
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "agent_type": task.agent_type.value,
        "objective_preview": task.objective[:200],
        "tenant_id": task.tenant_id,
        "user_id": task.user_id,
        "input_context": _walk(task.input_context),
        "expected_output_schema": task.expected_output_schema,
        "dependencies": [str(d) for d in task.dependencies],
        "max_tool_calls": task.max_tool_calls,
        "timeout_seconds": task.timeout_seconds,
    }