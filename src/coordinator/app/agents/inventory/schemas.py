# src/coordinator/app/agents/inventory/schemas.py

"""Pydantic schemas specific to the Inventory Agent output.

The Agent returns AgentResult (generic). The `result` dict inside it is
expected to conform to `InventoryResult` so that:
  - Deterministic validation can check structured fields.
  - Future Synthesis (Phase 3) can consume multiple agents uniformly.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InventoryRow(BaseModel):
    """One row of inventory data, as summarized by the Agent."""

    model_config = ConfigDict(extra="allow")  # forward-compatible with ERP fields

    sku: str | None = None
    warehouse: str | None = None
    quantity: float | None = None
    reorder_point: float | None = None
    last_transaction_at: str | None = None


class InventoryResult(BaseModel):
    """Structured result of an Inventory Agent task."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=8000)
    rows: list[InventoryRow] = Field(default_factory=list)
    tool_name: str | None = None
    row_count: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


__all__ = ["InventoryResult", "InventoryRow"]