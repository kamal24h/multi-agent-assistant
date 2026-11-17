# Architecture of multi agent Assistant

src/coordinator/app/
├── agents/                       # 🆕 (فاز ۱)
│   └── inventory/                # فقط Inventory Agent
│       ├── __init__.py
│       ├── agent.py              # run_inventory_agent(task: AgentTask) -> AgentResult
│       ├── prompts.py            # tool selection + summarization (منتقل از workflow)
│       └── schemas.py            # InventoryResult (Pydantic)
│
├── supervisor/                   # 🆕 (فاز ۱)
│   ├── __init__.py
│   ├── state.py                  # SupervisorState (TypedDict)
│   ├── task_contracts.py         # AgentTask, AgentResult, TaskStatus, Evidence
│   ├── complexity.py             # _is_complex_request (D9)
│   ├── graph.py                  # build_supervisor_graph()
│   └── policies.py               # MAX_TASKS, timeouts, safe prompt builder
│
├── graphs/                       # ✅ موجود (تغییر حداقلی)
│   ├── workflow.py               # + یک conditional edge "supervisor" در route_by_intent
│   └── state.py                  # + فیلدهای جدید (supervisor_result, ...)
│
├── routing/                      # ✅ موجود — دست‌نخورده
│   ├── __init__.py
│   ├── intent_classifier.py
│   ├── intent_schemas.py
│   ├── intent_prompts.py
│   ├── keyword_fallback.py
│   ├── clarification.py
│   ├── llm_factory.py
│   └── planning_prompts.py
│
├── services/                     # ✅ موجود — دست‌نخورده
│   ├── approval_store.py
│   ├── clarification_store.py
│   ├── llm_router.py
│   ├── mcp_client.py             # ← اینجا بماند (نه در app/mcp/)
│   ├── openai_service.py
│   ├── prompts.py
│   └── sanitization.py
│
├── terminology/                  # ✅ موجود — دست‌نخورده
│   ├── resolver.py
│   ├── normalizer.py
│   ├── context_builder.py
│   └── models.py
│
└── core/                         # ✅ موجود — تغییر حداقلی
    ├── config.py                 # + supervisor_enabled, supervisor_max_tasks, ...
    ├── schemas.py                # + فیلدهای جدید در ChatResponse (اختیاری)
    ├── guardrails.py
    └── clarification.py          # (فایل قدیمی backlog؛ حفظ شود)