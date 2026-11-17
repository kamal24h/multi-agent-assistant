# src/coordinator/app/supervisor/policies.py

"""Hard limits and safe-prompt builder for the Supervisor (Phase 1).

Per spec §7.3 and §10.1:
  - Bounded task count, retries, tool calls, timeouts.
  - Model policy is NOT overridden here; call sites use `answer_external_first`
    with existing stage names so existing LLM_POLICY__* envs still apply.
  - `build_safe_prompt` enforces the Coordinator's `openai_max_input_chars`
    before calling `answer_external_first`, preventing silent fallbacks to
    local model on oversized planning prompts.
"""
from __future__ import annotations

from app.core.config import settings


# ---- Hard limits (spec §7.3) ----
MAX_TASKS_PER_REQUEST: int = 2         # D2: conservative for Phase 1
MAX_TOOL_CALLS_PER_TASK: int = 2       # one call + one retry allowed
MAX_TASK_RETRIES: int = 0              # no retries in Phase 1
TASK_TIMEOUT_SECONDS: int = 90         # D2: covers 4 round-trips MCP + summarize
TOTAL_REQUEST_TIMEOUT_SECONDS: int = 180


# ---- Prompt safety (R1 from prior analysis) ----
def build_safe_prompt(prompt: str, *, safety_margin: int = 500) -> str:
    """Bound a prompt to Coordinator's openai_max_input_chars budget.

    If the prompt exceeds the budget, truncate the tail and append a marker.
    The caller MUST still treat this as a soft limit; long prompts indicate
    a planning error (too many tasks / too much context), not a user problem.
    """
    limit = max(1000, settings.openai_max_input_chars - safety_margin)
    if len(prompt) <= limit:
        return prompt
    return prompt[: limit - 20] + "\n...[truncated]"