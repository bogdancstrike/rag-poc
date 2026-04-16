# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Backend
make install          # pip install requirements + local QF framework wheel
make backend          # python main.py  (port 5100)
make infra            # docker compose up -d postgres elasticsearch jaeger
make up               # docker compose up -d  (all services)
make seed-es          # seed 2000 synthetic OSINT docs into ES

# Frontend
make frontend-install # cd frontend && npm install
make frontend         # cd frontend && npm run dev  (port 5173)

# Tests
make test             # all tests
make test-unit        # tests/unit/ only
make test-integration # tests/integration/ (skips slow markers)
pytest tests/unit/test_prompt_builder.py -v   # single test file
pytest tests/unit/test_prompt_builder.py::TestBuildChatMessages::test_returns_tuple_of_messages_and_system -v  # single test

# Lint (syntax check only, no linter configured)
make lint
```

## Architecture

### Backend (`src/`)

The backend uses **QF Framework** (a proprietary Flask/gevent wrapper in `dist/qf-1.0.2-py3-none-any.whl`). All HTTP handlers follow the signature `handler(app, operation, request, **kwargs) → (body, status_code)`. All endpoints are prefixed `/rag/`.

**Current layout** (pre-modulith):
```
src/
├── config.py                # All env-var config (Config class, class-level attrs)
├── api/endpoints.py         # ~2000-line monolith — all HTTP handlers
├── rag/
│   ├── llm_client.py        # OpenAI-compat wrapper (auto-discovers model from /v1/models)
│   ├── prompt_builder.py    # All prompt assembly (chat, insights, enrichment, translation)
│   ├── retriever.py         # Unified BM25/hybrid retrieval (ES or file backend)
│   └── insights_engine.py  # InsightsEngine + InsightsEventBus (SSE pub/sub)
├── session/
│   ├── models.py            # 9 SQLAlchemy ORM models + get_db() context manager
│   └── session_service.py  # CRUD for sessions, messages, saved searches, investigations
├── datasource/
│   ├── es_client.py         # ES8 wrapper: BM25, hybrid (RRF+KNN), aggregations, bulk copy
│   ├── embedding_client.py  # fastembed CPU wrapper (BAAI/bge-m3), GPU-free
│   └── file_loader.py       # In-memory JSONL/JSON/CSV/TXT backend
└── worker/
    ├── kafka_producer.py    # publish_task() with thread fallback when Kafka is down
    ├── kafka_consumer.py    # Consumer loop: semaphore-gated LLM tasks, unbounded fast tasks
    └── task_handlers.py     # dispatch_task() routes to per-type handler functions
```

**Planned modulith** (`monolith_todo.md` tracks progress):
```
src/
├── core/           # Config, DB engine/Base/get_db, logging, tracing
├── retrieval/      # es_client, embedding_client, file_loader, retriever
├── llm/            # client, prompts (all prompt builders)
├── chat/           # Session+Message ORM, session_service, RAG pipeline
├── insights/       # InsightsCache ORM, InsightsEngine, InsightsEventBus, task handlers
├── enrichment/     # DocumentEnrichment ORM, pipeline, ioc, geocoding, task handlers
├── investigations/ # Investigation+SavedSearch ORM, service, task handlers
├── tasking/        # Kafka producer, consumer, registry (task_type → handler, zero domain imports)
└── api/            # Thin controllers per domain (no business logic)
```

### Key patterns

**Task system**: Tasks flow `publish_task()` → Kafka topic → `kafka_consumer` → `dispatch_task()` → handler. Two topics: `llm_tasks` (LLM-heavy, semaphore-limited) and `fast_tasks` (ES aggregations, unbounded thread pool). When Kafka is unavailable, tasks run in daemon threads directly.

**InsightsEngine**: Non-blocking — `get_insights()` returns the current DB state immediately and triggers background work via Kafka if stale. The `InsightsEventBus` pub/sub pushes task status events to SSE subscribers per datasource.

**LLMClient**: Singleton that auto-discovers the model name and context window from the Ollama/SGLang `/v1/models` endpoint at startup. `complete_json()` uses `response_format={"type": "json_object"}` with retry at higher temperature on parse failure.

**DB access**: Always via `with get_db() as db:` context manager (auto-commit/rollback). ORM models live in `session/models.py`. Tests use SQLite in-memory by setting `DATABASE_URL=sqlite:///:memory:` before imports.

**Startup recovery** (`main.py → _recover_dangling_tasks`): On every start, insight tasks stuck in `pending`/`processing` are republished to Kafka; enrichment `processing` tasks are marked `error`; enrichment `pending` tasks fetch text from ES and republish.

### Infrastructure

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5432 | Sessions, messages, insights cache, enrichments, investigations |
| Elasticsearch | 9200 | Document storage and retrieval (indices: `qsint_docs*`, `inv_*`) |
| Kafka | 9094 | Task queue (topics: `qsint.rag.llm_tasks`, `qsint.rag.fast_tasks`) |
| SGLang / Ollama | 30000 / 11434 | LLM inference (OpenAI-compat API) |
| Jaeger | 4317 (OTLP) | Distributed tracing |
| Redis | 6379 | Framework cache (not used by RAG logic) |

### Frontend (`frontend/`)

React SPA (Vite + TypeScript + Ant Design). API calls go via `src/api/client.ts` (axios, base `/rag`). React Query handles caching and polling. Key hooks: `useInsights`, `useInvestigation`, `useDocuments`. The `InsightsPanel` component polls `_meta.is_processing` (not individual task statuses) to determine whether to show the synthesis banner.

### Testing approach

- **Unit tests**: Use SQLite in-memory for DB tests; mock all external services (Kafka, ES, LLM). `test_session_service.py` uses `init_db()` with a real SQLite engine.
- **Integration tests**: Require running infrastructure (Postgres, ES). Marked `slow` tests are skipped by default.
- **E2E tests**: Full stack (`tests/e2e/`).

Import paths in tests use `src.*` (e.g. `from src.rag.prompt_builder import PromptBuilder`).
