"""Supervisor package for selective hierarchical multi-agent orchestration.

Phase 1 scope:
  - Only InventoryAgent is supported.
  - Sequential delegation only (no parallel execution).
  - Conservative complexity gate (D9 revised): only ERP_DATA_QUERY with
    multiple entities and explicit complexity indicators enters Supervisor.
  - MIXED_QUERY remains on the existing `planning` route in Phase 1.
"""
from app.supervisor.task_contracts import (
    AgentTask,
    AgentResult,
    AgentType,
    TaskStatus,
)
from app.supervisor.state import SupervisorState

__all__ = [
    "AgentTask",
    "AgentResult",
    "AgentType",
    "TaskStatus",
    "SupervisorState",
]