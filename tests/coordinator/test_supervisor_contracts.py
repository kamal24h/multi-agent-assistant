# tests/coordinator/test_supervisor_contracts.py

"""Unit tests for Supervisor Task Contract (Phase 1)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from coordinator.app.supervisor.task_contracts import (
    AgentResult,
    AgentTask,
    AgentType,
    EvidenceItem,
    TaskStatus,
    sanitize_task_for_log,
)


def test_agent_task_minimal():
    task = AgentTask(
        agent_type=AgentType.INVENTORY,
        objective="موجودی SKU-11111 را بررسی کن",
        tenant_id="tenant-a",
        user_id="user-1",
    )
    assert task.task_id is not None
    assert task.max_tool_calls == 2
    assert task.timeout_seconds == 90


def test_agent_task_rejects_overlong_objective():
    with pytest.raises(ValidationError):
        AgentTask(
            agent_type=AgentType.INVENTORY,
            objective="x" * 3000,
            tenant_id="t",
            user_id="u",
        )


def test_agent_task_rejects_unsupported_agent_type():
    with pytest.raises(ValidationError):
        AgentTask(
            agent_type="sales",  # type: ignore[arg-type]
            objective="x",
            tenant_id="t",
            user_id="u",
        )


def test_sanitize_task_for_log_hides_authorization():
    task = AgentTask(
        agent_type=AgentType.INVENTORY,
        objective="موجودی",
        tenant_id="t",
        user_id="u",
        input_context={
            "authorization": "Bearer secret",
            "nested": {"token": "should-be-redacted"},
            "safe": "ok",
        },
    )
    sanitized = sanitize_task_for_log(task)
    assert sanitized["input_context"]["authorization"] == "[REDACTED]"
    assert sanitized["input_context"]["nested"]["token"] == "[REDACTED]"
    assert sanitized["input_context"]["safe"] == "ok"


def test_agent_result_roundtrip():
    task_id = uuid4()
    ev = EvidenceItem(
        source_type="erp_mcp",
        tool_name="inventory_read",
        arguments_hash="a" * 64,
        row_count=3,
        structured_preview='{"items":[...]}',
        called_at="2026-11-17T12:00:00+00:00",
    )
    result = AgentResult(
        task_id=task_id,
        agent_type=AgentType.INVENTORY,
        tenant_id="t",
        user_id="u",
        status=TaskStatus.SUCCESS,
        result={"answer": "موجودی ۱۰۰ عدد"},
        evidence=[ev],
        execution_metrics={"duration_seconds": 2.3, "tool_calls": 1},
    )
    assert result.model_dump()["task_id"] == task_id