# QSINT RAG — Changelog

> Tracks what is implemented, what is working, and what is still pending.
> Updated: 2026-04-10

---

## [0.1.0] — 2026-04-10 — Initial Implementation

### ✅ Done

#### Infrastructure
- [x] **`docker-compose.yml`** — Full environment: PostgreSQL 15, Elasticsearch 8.13, Ollama (GPU), Jaeger (OTLP tracing)
- [x] **`Dockerfile`** — Multi-stage Python 3.12 slim image, installs QF wheel + requirements
- [x] **`frontend/Dockerfile.dev`** — Node 20 dev container with hot reload
- [x] **`.env.example`** — All environment variables documented with sensible defaults
- [x] **`Makefile`** — `infra`, `up`, `down`, `backend`, `frontend`, `test`, `seed-es` targets
- [x] **Ollama GPU support** — nvidia-container-toolkit passthrough, `OLLAMA_KEEP_ALIVE=24h`
- [x] **Model pulled** — `qwen2.5:7b` running at `http://localhost:11434/v1`
- [x] **Elasticsearch seeded** — 30,000 realistic QSINT intelligence documents (Faker-generated)

#### Backend — QF Framework
- [x] **`main.py`** — Standard QF `FrameworkApp` entry point, `enable_etl=False`, gevent monkey-patch
- [x] **`maps/endpoint.json`** — All 11 API routes declared (QF dynamic endpoint system)
- [x] **`src/config.py`** — Env-driven config including Redis/Kafka stubs required by QF framework at import
- [x] **API prefix** — QF registers routes under `/rag/` namespace (e.g. `/rag/v1/chat`)

#### Backend — Datasource
- [x] **`src/datasource/es_client.py`** — Elasticsearch 8.x client with BM25 search, random sampling, index health, auto-create index
- [x] **`src/datasource/file_loader.py`** — Loads JSONL/JSON/CSV/TXT corpus files, in-memory BM25 search via `rank_bm25`
- [x] **ES client version** — Pinned to `elasticsearch>=8.13,<9` (v9 sends incompatible headers to ES 8)

#### Backend — RAG Core
- [x] **`src/rag/retriever.py`** — Unified interface: delegates to ES or file loader based on `DATASOURCE_TYPE`; singleton pattern
- [x] **`src/rag/llm_client.py`** — OpenAI-compatible client pointing at Ollama (`http://localhost:11434/v1`); sync `complete()`, streaming `stream()` via `create(stream=True)`, JSON-mode `complete_json()`
- [x] **`src/rag/prompt_builder.py`** — Assembles chat messages with XML-tagged context chunks + conversation history; insights analysis prompt
- [x] **`src/rag/insights_engine.py`** — LLM-powered intelligence generation: samples corpus, calls LLM for hot_topics/narratives/trends/entities/anomalies; Postgres cache with TTL; thread-safe with lock

#### Backend — Session Management
- [x] **`src/session/models.py`** — SQLAlchemy ORM: `Session`, `Message`, `InsightsCache` tables; `@contextmanager get_db()`
- [x] **`src/session/session_service.py`** — Full CRUD: create/get/list/delete/rename sessions; append/get messages; auto-title from first user message

#### Backend — API Endpoints (all tested)
- [x] `GET  /rag/health` — full dependency health (ES + LLM status)
- [x] `GET  /rag/liveness` — lightweight liveness probe
- [x] `POST /rag/v1/chat` — synchronous RAG chat (retrieve → LLM → return)
- [x] `POST /rag/v1/chat/stream` — SSE streaming chat (retrieve → stream deltas → persist)
- [x] `GET  /rag/v1/insights` — cached intelligence report (hot topics, narratives, trends, entities, anomalies)
- [x] `POST /rag/v1/insights/refresh` — force regeneration
- [x] `GET/POST /rag/v1/sessions` — list / create sessions
- [x] `GET/DELETE/PATCH /rag/v1/sessions/<id>` — get / delete / rename session
- [x] `GET /rag/v1/sessions/<id>/messages` — full message history
- [x] `GET /rag/v1/datasource/status` — ES/file connectivity info

#### Backend — Seed Script
- [x] **`scripts/seed_elasticsearch.py`** — Seeds 30,000 Faker-generated QSINT intelligence documents into ES via bulk API; supports `--count`, `--batch`, `--clear` flags; progress logging

#### Frontend — React + Vite + Ant Design
- [x] **`frontend/package.json`** — antd v6, @ant-design/plots, @ant-design/x, @tanstack/react-query, zustand, react-markdown, react-router-dom
- [x] **`frontend/vite.config.ts`** — Dev proxy to `/rag/*` backend; dual build (app + lib mode)
- [x] **`frontend/src/RagModule.tsx`** — Public component: `<RagModule baseUrl="" datasource="" />` with tabs (Intelligence / Chat), dark/light theme
- [x] **`frontend/src/index.ts`** — Library entry point exports `RagModule`
- [x] **API clients** — `client.ts` (axios + `/rag` base prefix), `insights.ts`, `sessions.ts`, `chat.ts` (SSE fetch streaming)
- [x] **Stores** — `themeStore.ts` (dark/light, persisted), `sessionStore.ts` (active session, messages, streaming delta accumulation)
- [x] **Hooks** — `useInsights`, `useRefreshInsights`, `useSessions`, `useCreateSession`, `useDeleteSession`, `useRenameSession`, `useMessages`, `useChat`
- [x] **InsightsPanel** — Hot topics (bubble chart), Trends (bar chart), Narratives (cards with sentiment + "Ask about this" CTA), Entities (bar chart), Anomalies (alert list)
- [x] **Charts** — `TopicBubbleChart` (Scatter), `TrendAreaChart` (Bar), `EntityBarChart` (Bar) via @ant-design/plots
- [x] **NarrativeCard** — Sentiment badge, expandable description, evidence doc IDs, "Ask about this" → pre-fills chat
- [x] **ChatPanel** — SessionSidebar (create/rename/delete), message list, streaming MessageBubble with source citations, SSE send/stop
- [x] **MessageBubble** — Markdown rendering (react-markdown), collapsible sources drawer, streaming cursor animation
- [x] **SessionSidebar** — Inline rename (double-click), delete with confirm, session list with message counts
- [x] **Frontend build** — Compiles cleanly (TypeScript + Vite production build verified)

#### Tests
- [x] **55 unit tests** — `test_prompt_builder.py`, `test_file_loader.py`, `test_session_service.py`, `test_insights_engine.py` — all passing
- [x] **5 E2E tests** — sync chat, streaming chat, session history, insights generation, insights refresh — all passing against live backend
- [x] **Integration test skeleton** — `tests/integration/test_endpoints.py` (Flask test client + mocked LLM/ES)

---

### ⚠️ Known Issues / Bugs Fixed
- **ES client version** — `elasticsearch>=9` sends `compatible-with=9` headers rejected by ES 8 server → pinned to `>=8.13,<9`
- **QF framework Config attrs** — ETL module reads `REDIS_HOST`, `WORKER_NAME` etc. at module import time even with `enable_etl=False` → added stubs to `Config`
- **`get_db()` context manager** — Missing `@contextmanager` decorator on generator function → added
- **Streaming API** — Used `client.chat.completions.stream()` (beta context manager that yields `ChunkEvent`) instead of `create(stream=True)` (yields `ChatCompletionChunk`) → fixed
- **API route prefix** — QF framework prefixes routes with namespace name `/rag/` → updated frontend client base URL and vite proxy
- **TypeScript** — `import.meta.env` type error in standalone harness → cast to `(import.meta as any).env`

---

### 🔲 Not Yet Done / Future Work

#### Backend
- [ ] **Redis not running** — Docker compose includes Redis, but no Redis container is in the infra stack (QF framework won't actually use it since ETL is disabled). Add if caching is needed.
- [ ] **Alembic migrations** — Currently using `metadata.create_all()`. Should add Alembic for schema versioning in production.
- [ ] **Rate limiting** — No per-IP or per-session rate limits on chat endpoints.
- [ ] **Authentication** — No auth layer. Add API key or JWT for production deployment.
- [ ] **KNN / vector search** — ES client detects dense_vector fields but falls back to BM25. Add embedding generation pipeline (e.g. via Ollama `nomic-embed-text` model) for semantic search.
- [ ] **Insights scheduling** — Insights are generated on-demand. Add a background scheduler (APScheduler or cron) to regenerate periodically.
- [ ] **Streaming with gevent** — gevent monkey-patch may conflict with Ollama's streaming in some configurations. Tested as working but needs load testing.
- [ ] **Multi-datasource routing** — Each chat message goes to one datasource. Support mixing multiple indices/files.

#### Frontend
- [ ] **npm `eslint` config** — `eslint.config.js` not created (minor; no lint errors in build).
- [ ] **E2E browser tests** — No Playwright/Cypress tests for the UI.
- [ ] **Responsive layout** — InsightsPanel uses fixed column widths; not fully mobile-optimised.
- [ ] **Export / download** — No way to export chat history or insights report as PDF/JSON.
- [ ] **Real-time insights push** — Currently poll-based (react-query stale time). Could add WebSocket push when insights refresh.
- [ ] **@ant-design/x Sender** — ChatPanel uses plain antd Input instead of the richer `@ant-design/x` Sender component (file attachments, voice input).

#### Infrastructure
- [ ] **Production WSGI** — Currently using Flask dev server. Should switch to gunicorn+gevent or uWSGI for production.
- [ ] **ES cluster health** — Index is `yellow` (single-node, no replicas). Normal for dev; production should have replicas.
- [ ] **Frontend container build** — `frontend/Dockerfile.dev` runs `vite dev`. Add production Nginx build for deployment.
- [ ] **Secret management** — `.env` file contains secrets in plaintext. Use Docker secrets or Vault for production.
- [ ] **HTTPS / reverse proxy** — No TLS. Add Nginx or Traefik in production.

---

### Quick Start

```bash
# 1. Start infrastructure
docker compose up -d postgres elasticsearch ollama jaeger

# 2. Pull LLM model (takes 5-10 min depending on bandwidth)
make pull-model

# 3. Seed 30k documents
python3 scripts/seed_elasticsearch.py --count 30000

# 4. Start backend (local)
python3 main.py

# 5. Start frontend (local)
cd frontend && npm install && npm run dev
# → http://localhost:5173

# 6. Run tests
make test-unit        # 55 fast unit tests
make test-e2e         # 5 E2E tests (requires backend running)
```

### Endpoints Summary
| Method | URL | Description |
|--------|-----|-------------|
| GET    | `/rag/health` | Dependency health check |
| GET    | `/rag/liveness` | Liveness probe |
| POST   | `/rag/v1/chat` | Synchronous RAG chat |
| POST   | `/rag/v1/chat/stream` | SSE streaming RAG chat |
| GET    | `/rag/v1/insights` | Cached intelligence report |
| POST   | `/rag/v1/insights/refresh` | Force regenerate insights |
| GET/POST | `/rag/v1/sessions` | List / create sessions |
| GET/DELETE/PATCH | `/rag/v1/sessions/<id>` | Get / delete / rename |
| GET    | `/rag/v1/sessions/<id>/messages` | Full chat history |
| GET    | `/rag/v1/datasource/status` | Datasource connectivity |
