# Modulith Migration Tracker

## Goal
Restructure `src/` into domain-aligned modules while keeping a single deployable unit.
Each step preserves all 116 unit tests. Tests are updated to new paths at Step 10.

## Dependency graph (enforced)
```
core          ← nobody
retrieval     → core
llm           → core
chat          → core, retrieval, llm
insights      → core, retrieval, llm, tasking
enrichment    → core, retrieval, llm, tasking
investigations→ core, retrieval, tasking
tasking       → core   (zero domain imports — handlers registered via registry)
api           → all modules
```

---

## Steps

- [x] Step 0 — Baseline: 116 unit tests passing
- [x] Step 1 — `src/core/` : extract DB infrastructure from `session/models.py`
- [x] Step 2 — `src/retrieval/` : move `datasource/` + `rag/retriever.py`
- [x] Step 3 — `src/llm/` : move `rag/llm_client.py` + `rag/prompt_builder.py`
- [x] Step 4 — `src/tasking/` : move `worker/` + add `registry.py`
- [x] Step 5 — `src/chat/` : extract Session/Message ORM + session service
- [x] Step 6 — `src/insights/` : move InsightsCache ORM + `rag/insights_engine.py`
- [x] Step 7 — `src/enrichment/` : extract DocumentEnrichment ORM + pipeline from endpoints
- [x] Step 8 — `src/investigations/` : extract remaining ORM models + investigation service
- [x] Step 9 — `src/api/` : split `endpoints.py` into thin domain controllers
- [x] Step 10 — Update `tests/` to use new import paths; run full suite
- [x] Step 11 — Update `README.md` with new architecture

---

## Old → New path map (shims kept until Step 10)

| Old path | New canonical path |
|---|---|
| `src/config.py` | unchanged |
| `src/session/models.py` | shim → `src/core/db.py` (infra) + domain `models.py` files |
| `src/session/session_service.py` | shim → `src/chat/service.py` + `src/investigations/service.py` |
| `src/datasource/es_client.py` | shim → `src/retrieval/es_client.py` |
| `src/datasource/embedding_client.py` | shim → `src/retrieval/embedding_client.py` |
| `src/datasource/file_loader.py` | shim → `src/retrieval/file_loader.py` |
| `src/rag/retriever.py` | shim → `src/retrieval/retriever.py` |
| `src/rag/llm_client.py` | shim → `src/llm/client.py` |
| `src/rag/prompt_builder.py` | shim → `src/llm/prompts.py` |
| `src/rag/insights_engine.py` | shim → `src/insights/engine.py` |
| `src/worker/kafka_producer.py` | shim → `src/tasking/producer.py` |
| `src/worker/kafka_consumer.py` | shim → `src/tasking/consumer.py` |
| `src/worker/task_handlers.py` | shim → `src/tasking/handlers.py` |
| `src/api/endpoints.py` | shim → `src/api/` domain controllers |

---

## Notes
- `src/core/db.py`'s `init_db()` imports all domain model modules before `create_all()` to ensure table registration.
- `src/tasking/registry.py` maps `task_type → handler`. Domain task modules register handlers with `@register(...)`. App entry point imports all task modules to trigger registration.
- All shims use `from src.newmodule import *` pattern.
