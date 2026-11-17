# tests/coordinator/test_complexity_gate.py

"""Unit tests for conservative complexity gate (D9 revised)."""
from __future__ import annotations

from types import SimpleNamespace

from coordinator.app.supervisor.complexity import is_complex_request


def _state(intent: str, entities: dict | None, prompt: str):
    return {
        "intent_decision": SimpleNamespace(
            intent=intent,
            entities=entities or {},
            needs_clarification=False,
        ),
        "request": SimpleNamespace(prompt=prompt),
    }


def test_returns_false_for_simple_erp_data():
    state = _state("ERP_DATA_QUERY", {"sku": "SKU-1"}, "موجودی SKU-1 چقدر است؟")
    assert is_complex_request(state) is False


def test_returns_false_for_mixed_query():
    state = _state(
        "MIXED_QUERY",
        {"a": 1, "b": 2},
        "وضعیت سفارش را مقایسه کن و بگو همچنین چه رویه‌ای دارد" * 2,
    )
    assert is_complex_request(state) is False  # Phase 1: goes to planning, not supervisor


def test_returns_false_for_erp_action():
    state = _state("ERP_ACTION", {"a": 1, "b": 2}, "فاکتور را حذف کن و همچنین گزارش بده")
    assert is_complex_request(state) is False


def test_returns_true_for_complex_erp_data():
    prompt = "موجودی SKU-11111 و SKU-22222 را مقایسه کن و همچنین نقطه سفارش را بگو " * 2
    state = _state("ERP_DATA_QUERY", {"sku_a": "SKU-1", "sku_b": "SKU-2"}, prompt)
    assert is_complex_request(state) is True


def test_returns_false_when_only_one_entity():
    prompt = "موجودی SKU-11111 را مقایسه کن و همچنین تحلیل کن " * 3
    state = _state("ERP_DATA_QUERY", {"sku": "SKU-1"}, prompt)
    assert is_complex_request(state) is False


def test_returns_false_without_complexity_indicator():
    prompt = "وضعیت موجودی انبار مرکزی را بررسی کن و بگو چقدر است " * 3
    state = _state("ERP_DATA_QUERY", {"a": 1, "b": 2}, prompt)
    assert is_complex_request(state) is False