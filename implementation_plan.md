# QSINT RAG Module — Implementation Plan

> **Date:** 2026-04-10  
> **Stack:** Python 3.12 · QF Framework v6.6 · Flask-RESTX · Claude claude-sonnet-4-6 (Anthropic) · Elasticsearch 8 · PostgreSQL 15 · React 19 · Vite · Ant Design v6 · @ant-design/plots · @ant-design/x  
> **Working dir:** `/home/bogdan/workspace/dev/rag-poc`

---

## 1. Overview

A self-contained RAG (Retrieval-Augmented Generation) module for the QSINT platform.

**On open:** the UI surfaces AI-generated intelligence reports — hot topics, trending narratives, anomalies, entity clusters — as both prose and interactive charts, driven by live data from an Elasticsearch index (or a local file datasource).

**Chat panel:** the user can ask free-form questions; the backend retrieves the most relevant document chunks from ES, passes them as context to Claude, streams the answer back, and persists the full session to Postgres.

**Modular design:** the React component tree is a standalone npm package (`@qsint/rag-ui`) that can be mounted into any project with `<RagModule baseUrl="..." />`.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser                                            │
│  ┌───────────────────────────────────────────────┐  │
│  │  <RagModule>                                  │  │
│  │  ├── InsightsPanel  (hot topics, trends)      │  │
│  │  │   ├── NarrativeCards  (text)               │  │
│  │  │   └── TrendCharts     (@ant-design/plots)  │  │
│  │  └── ChatPanel      (@ant-design/x Bubble)    │  │
│  └───────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────┘
                        │ HTTP / SSE
┌───────────────────────▼─────────────────────────────┐
│  QSINT RAG Backend  (QF Framework)                  │
│  main.py + maps/endpoint.json                       │
│                                                     │
│  src/                                               │
│  ├── api/endpoints.py          ← QF handlers        │
│  ├── config.py                                      │
│  ├── rag/                                           │
│  │   ├── retriever.py          ← ES / file search   │
│  │   ├── llm_client.py         ← Anthropic SDK      │
│  │   ├── prompt_builder.py     ← context assembly   │
│  │   └── insights_engine.py   ← topics/trends LLM  │
│  ├── session/                                       │
│  │   ├── models.py             ← SQLAlchemy ORM     │
│  │   └── session_service.py   ← CRUD + history      │
│  └── datasource/                                    │
│      ├── es_client.py                               │
│      └── file_loader.py                             │
└──────────┬──────────────────┬───────────────────────┘
           │                  │
    ┌──────▼──────┐    ┌──────▼──────┐
    │Elasticsearch│    │  PostgreSQL  │
    │  (data)     │    │  (sessions)  │
    └─────────────┘    └─────────────┘
```

---

## 3. Project Layout

```
rag-poc/
├── main.py                         # QF FrameworkApp entry point
├── maps/
│   └── endpoint.json               # All API routes declared here
├── src/
│   ├── __init__.py
│   ├── config.py                   # Env-driven config (like ai-flow-orchestrator)
│   ├── api/
│   │   ├── __init__.py
│   │   └── endpoints.py            # QF handler functions (app, operation, request, **kwargs)
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── retriever.py            # ES vector/keyword hybrid search
│   │   ├── llm_client.py           # Anthropic SDK wrapper (streaming + non-streaming)
│   │   ├── prompt_builder.py       # Assemble system+user prompts from retrieved chunks
│   │   └── insights_engine.py      # Periodically generate hot topics / trends / narratives
│   ├── session/
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy: Session, Message tables
│   │   └── session_service.py      # Create session, append messages, list history
│   └── datasource/
│       ├── __init__.py
│       ├── es_client.py            # Elasticsearch 8 client + index helpers
│       └── file_loader.py          # Load JSON/CSV/JSONL/text files as document chunks
├── frontend/                       # React + Vite + Antd module
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx                # Standalone dev harness
│       ├── index.ts                # Library entry point (exports RagModule)
│       ├── RagModule.tsx           # Root component — accepts baseUrl prop
│       ├── api/
│       │   ├── client.ts
│       │   ├── insights.ts
│       │   ├── chat.ts             # SSE streaming chat
│       │   └── sessions.ts
│       ├── components/
│       │   ├── layout/
│       │   │   └── RagShell.tsx
│       │   ├── insights/
│       │   │   ├── InsightsPanel.tsx
│       │   │   ├── NarrativeCard.tsx
│       │   │   ├── TopicBubbleChart.tsx
│       │   │   ├── TrendAreaChart.tsx
│       │   │   └── EntityBarChart.tsx
│       │   └── chat/
│       │       ├── ChatPanel.tsx
│       │       ├── MessageBubble.tsx
│       │       └── SessionSidebar.tsx
│       ├── hooks/
│       │   ├── useInsights.ts
│       │   ├── useChat.ts          # SSE hook
│       │   └── useSessions.ts
│       ├── stores/
│       │   ├── themeStore.ts       # dark/light (same pattern as ai-flow-orchestrator)
│       │   └── sessionStore.ts
│       └── types/
│           └── index.ts
├── tests/
│   ├── unit/
│   │   ├── test_retriever.py
│   │   ├── test_prompt_builder.py
│   │   ├── test_insights_engine.py
│   │   └── test_session_service.py
│   ├── integration/
│   │   ├── test_es_client.py
│   │   ├── test_endpoints.py       # Flask test client
│   │   └── test_session_db.py
│   └── e2e/
│       ├── test_chat_flow.py       # Full chat: POST → stream → Postgres verify
│       └── test_insights_flow.py
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
├── Makefile
└── docs/
    ├── architecture.md
    └── api_reference.md
```

---

## 4. Backend Implementation

### 4.1 `main.py`

Mirrors `ai-flow-orchestrator/main.py` exactly — gevent monkey-patch first, then `FrameworkApp` with `FrameworkSettings`. No Kafka needed (RAG is request/response + SSE), so `enable_etl=False`.

```python
# main.py — entry point (standard QF pattern)
settings = FrameworkSettings(
    enable_etl=False,
    enable_api=True,
    enable_dynamic_endpoints=True,
    api_host="0.0.0.0",
    api_port=Config.API_PORT,
    api_title="QSINT RAG API",
    endpoint_json_path="maps/endpoint.json",
    enable_tracing=Config.ENABLE_TRACING,
    otlp_endpoint=Config.OTLP_ENDPOINT,
    service_name="qsint-rag",
)
fw = FrameworkApp(settings, app_root=BASE_DIR)
handles = fw.run()
handles.app.run(host=settings.api_host, port=settings.api_port, debug=False)
```

### 4.2 `maps/endpoint.json`

All routes declared here — QF framework auto-wires them to handler functions.

```json
{
  "namespaces": [
    { "name": "rag", "description": "QSINT RAG API" }
  ],
  "models": { "Empty": {} },
  "endpoints": [
    {
      "namespace": "rag",
      "operation_name": "health",
      "model_name": "Empty",
      "request_method": ["GET"],
      "api_url": "/health",
      "exec_method": { "module_name": "api.endpoints", "method_name": "health_check" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_chat",
      "model_name": "Empty",
      "request_method": ["POST"],
      "api_url": "/v1/chat",
      "exec_method": { "module_name": "api.endpoints", "method_name": "chat_handler" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_chat_stream",
      "model_name": "Empty",
      "request_method": ["POST"],
      "api_url": "/v1/chat/stream",
      "exec_method": { "module_name": "api.endpoints", "method_name": "chat_stream_handler" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_insights",
      "model_name": "Empty",
      "request_method": ["GET"],
      "api_url": "/v1/insights",
      "exec_method": { "module_name": "api.endpoints", "method_name": "insights_handler" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_insights_refresh",
      "model_name": "Empty",
      "request_method": ["POST"],
      "api_url": "/v1/insights/refresh",
      "exec_method": { "module_name": "api.endpoints", "method_name": "insights_refresh_handler" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_sessions",
      "model_name": "Empty",
      "request_method": ["GET", "POST"],
      "api_url": "/v1/sessions",
      "exec_method": { "module_name": "api.endpoints", "method_name": "sessions_handler" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_session_detail",
      "model_name": "Empty",
      "request_method": ["GET", "DELETE"],
      "api_url": "/v1/sessions/<session_id>",
      "exec_method": { "module_name": "api.endpoints", "method_name": "session_detail_handler" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_session_messages",
      "model_name": "Empty",
      "request_method": ["GET"],
      "api_url": "/v1/sessions/<session_id>/messages",
      "exec_method": { "module_name": "api.endpoints", "method_name": "session_messages_handler" }
    },
    {
      "namespace": "rag",
      "operation_name": "v1_datasource_status",
      "model_name": "Empty",
      "request_method": ["GET"],
      "api_url": "/v1/datasource/status",
      "exec_method": { "module_name": "api.endpoints", "method_name": "datasource_status_handler" }
    }
  ]
}
```

### 4.3 `src/config.py`

```python
class Config:
    # App
    API_PORT = int(os.getenv("API_PORT", "5100"))
    DEV_MODE = os.getenv("DEV_MODE", "true").lower() in ("1", "true", "yes")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

    # PostgreSQL
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://qf:qf@localhost:5432/qsint_rag")

    # Elasticsearch
    ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
    ES_INDEX = os.getenv("ES_INDEX", "qsint_docs")
    ES_USER = os.getenv("ES_USER", "")
    ES_PASSWORD = os.getenv("ES_PASSWORD", "")

    # File datasource (alternative to ES)
    DATASOURCE_TYPE = os.getenv("DATASOURCE_TYPE", "es")  # "es" | "file"
    FILE_DATASOURCE_PATH = os.getenv("FILE_DATASOURCE_PATH", "./data/corpus.jsonl")

    # Anthropic / LLM
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))  # chunks retrieved per query

    # Insights cache (seconds)
    INSIGHTS_CACHE_TTL = int(os.getenv("INSIGHTS_CACHE_TTL", "1800"))  # 30 min
    INSIGHTS_MAX_DOCS = int(os.getenv("INSIGHTS_MAX_DOCS", "200"))     # sampled for topic analysis

    # Tracing
    ENABLE_TRACING = os.getenv("ENABLE_TRACING", "false").lower() in ("1", "true", "yes")
    OTLP_ENDPOINT = os.getenv("QSINT_OTLP_ENDPOINT", "http://localhost:4317")
```

### 4.4 `src/datasource/es_client.py`

Wraps Elasticsearch 8 Python client.

**Key methods:**
- `search(query: str, top_k: int) -> list[dict]` — BM25 keyword search + optional KNN (if embeddings field present). Returns list of `{id, text, score, metadata}`.
- `get_sample_docs(n: int) -> list[dict]` — random sample for insights generation.
- `get_index_stats() -> dict` — doc count, field list, index health.
- `test_connection() -> bool`

### 4.5 `src/datasource/file_loader.py`

Loads local corpus files as document chunks.

**Supported formats:** `.jsonl` (one doc per line), `.json` (array or object), `.csv`, `.txt` (split by paragraph).

**Key methods:**
- `load_chunks(path: str) -> list[dict]` — reads and normalizes to `{id, text, metadata}`.
- `search(query: str, top_k: int, chunks: list) -> list[dict]` — TF-IDF BM25-style in-memory search using `rank_bm25`.

### 4.6 `src/rag/retriever.py`

Unified retrieval interface — delegates to ES or file loader based on `Config.DATASOURCE_TYPE`.

```python
class Retriever:
    def retrieve(self, query: str, top_k: int = None) -> list[dict]:
        """Retrieve top_k most relevant chunks for a query.
        
        Returns list of dicts: {id, text, score, source, metadata}
        Handles both ES and file sources transparently.
        """
```

### 4.7 `src/rag/prompt_builder.py`

Assembles the system + user prompt for Claude.

**System prompt template:**
```
You are QSINT, an intelligence analyst assistant.
Answer questions based ONLY on the provided context documents.
If the answer is not in the context, say so — do not hallucinate.
Cite document IDs when referencing specific information.
```

**Key method:**
- `build_messages(user_query: str, chunks: list[dict], history: list[dict]) -> list[dict]`
  - Formats retrieved chunks as `<doc id="..." score="...">text</doc>` XML blocks.
  - Appends conversation history (last N turns from Postgres).
  - Returns Anthropic-compatible `messages` list.

### 4.8 `src/rag/llm_client.py`

Thin wrapper around `anthropic.Anthropic`.

```python
class LLMClient:
    def complete(self, messages: list, system: str) -> str:
        """Synchronous completion. Returns full text."""

    def stream(self, messages: list, system: str) -> Generator[str, None, None]:
        """Yields text delta chunks for SSE streaming."""
```

Uses `claude-sonnet-4-6` by default. Instruments with OTLP span via `framework.tracing.get_tracer()`.

### 4.9 `src/rag/insights_engine.py`

Generates structured intelligence from the data corpus periodically or on-demand.

**Algorithm:**
1. Sample up to `INSIGHTS_MAX_DOCS` recent documents from ES/file.
2. Ask Claude to analyze the sample and return JSON with:
   - `hot_topics`: list of `{topic, count_estimate, summary, sentiment}`
   - `narratives`: list of `{title, description, evidence_docs}`
   - `trends`: list of `{label, direction, change_pct, time_period}`
   - `entities`: list of `{name, type, frequency, related}`
   - `anomalies`: list of `{description, docs}`
3. Cache result in Postgres (`insights` table) with TTL.

```python
class InsightsEngine:
    def get_insights(self, force_refresh: bool = False) -> dict:
        """Return cached insights or generate fresh ones if stale.
        
        Checks Postgres for cached entry. If expired or force_refresh,
        calls _generate() then stores result. Thread-safe via DB row lock.
        """

    def _generate(self) -> dict:
        """Sample corpus, build analysis prompt, call Claude, parse JSON response."""
```

### 4.10 `src/session/models.py`

SQLAlchemy ORM models.

```python
class Session(Base):
    __tablename__ = "rag_sessions"
    id          = Column(String, primary_key=True, default=lambda: str(uuid4()))
    title       = Column(String, nullable=True)           # auto-generated or user-set
    datasource  = Column(String, default="default")       # which index/file
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, onupdate=datetime.utcnow)
    messages    = relationship("Message", back_populates="session", order_by="Message.created_at")

class Message(Base):
    __tablename__ = "rag_messages"
    id          = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id  = Column(String, ForeignKey("rag_sessions.id", ondelete="CASCADE"))
    role        = Column(String)   # "user" | "assistant"
    content     = Column(Text)
    sources     = Column(JSON)     # list of retrieved chunk IDs used
    created_at  = Column(DateTime, default=datetime.utcnow)
    session     = relationship("Session", back_populates="messages")

class InsightsCache(Base):
    __tablename__ = "rag_insights_cache"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    datasource  = Column(String, default="default")
    payload     = Column(JSON)     # the full insights dict
    generated_at = Column(DateTime, default=datetime.utcnow)
```

### 4.11 `src/api/endpoints.py`

QF-pattern handlers — signature `(app, operation, request, **kwargs)`.

**`chat_stream_handler`** — The most important endpoint. Uses Flask's `Response(stream_with_context(...), mimetype="text/event-stream")` to stream SSE deltas from Claude.

```
POST /v1/chat/stream
Body: { session_id?: string, message: string }

1. Get or create session in Postgres.
2. Append user message to DB.
3. Load last N messages from session history.
4. Call Retriever.retrieve(message, top_k=RAG_TOP_K).
5. Build prompt via PromptBuilder.
6. Stream LLMClient.stream() as SSE: data: {"delta": "..."}\n\n
7. On stream end: persist full assistant message + sources to DB.
8. Flush final SSE event: data: {"done": true, "message_id": "..."}\n\n
```

**`insights_handler`** — `GET /v1/insights` returns cached insights JSON.

**`insights_refresh_handler`** — `POST /v1/insights/refresh` forces regeneration.

---

## 5. Frontend Implementation

### 5.1 Modular Design

The frontend is built as a **library** (`frontend/src/index.ts` exports `RagModule`) AND as a standalone app (`frontend/src/main.tsx` mounts it for dev/demo).

```tsx
// Library usage in another project:
import { RagModule } from '@qsint/rag-ui'

<RagModule
  baseUrl="http://localhost:5100"
  theme="dark"
  defaultDatasource="qsint_docs"
/>
```

`vite.config.ts` is configured for dual build:
- `lib` mode produces `dist/rag-ui.es.js` + `dist/rag-ui.umd.js`
- `app` mode produces the standalone dev harness

### 5.2 `RagModule.tsx` — Root Component

```tsx
// RagModule is the single export. Takes baseUrl + optional theme/datasource props.
// Wraps everything in AntD ConfigProvider (dark/light), QueryClientProvider, ApiContext.
// Layout: two-column (ResizablePanels) — left: InsightsPanel, right: ChatPanel
// On mount: triggers useInsights() which fetches /v1/insights
```

### 5.3 `InsightsPanel` — Intelligence Dashboard

Top section of the panel. Auto-loads on mount. Shows a loading skeleton while fetching.

**Layout (Row/Col grid, mirrors DashboardPage.tsx style):**

```
┌─────────────────────────────────────────────────────┐
│  [Refresh] [Last updated: 2 min ago]                │
├─────────────────┬───────────────────────────────────┤
│  Hot Topics     │  Trend Area Chart                 │
│  (Tag cloud /   │  (topic mentions over time)       │
│   bubble chart) │                                   │
├─────────────────┴───────────────────────────────────┤
│  Narratives (Card list with sentiment badge)        │
├─────────────────┬───────────────────────────────────┤
│  Entities       │  Anomalies                        │
│  (Bar chart)    │  (Alert list)                     │
└─────────────────┴───────────────────────────────────┘
```

**Charts** use `@ant-design/plots` (same library already used in ai-flow-orchestrator):
- `TopicBubbleChart` — Scatter/Bubble plot: x=sentiment, y=frequency, size=prominence
- `TrendAreaChart` — Area chart: time vs. mention count per narrative
- `EntityBarChart` — Horizontal Bar: entity name vs. occurrence count

**NarrativeCard** — AntD `Card` with `Tag` (sentiment: success/warning/error), title, summary text, and "Ask about this" button that pre-populates the chat input.

### 5.4 `ChatPanel` — Conversational RAG

Right panel. Uses **`@ant-design/x`** `Bubble.List` for message display (already in ai-flow-orchestrator's deps at `@ant-design/x: ^2.5.0`).

**Components:**
- `SessionSidebar` — collapsible left list of past sessions (loaded from `/v1/sessions`), with delete and rename.
- `ChatPanel` — main chat area with `Bubble.List` + `Sender` input from `@ant-design/x`.
- `MessageBubble` — renders markdown (using `marked` or `react-markdown`), shows collapsible "Sources" drawer with retrieved chunk previews.

**Streaming:** `useChat` hook reads SSE from `/v1/chat/stream` using the native `EventSource` API (or `fetch` with `ReadableStream` for POST support). Deltas are appended to an optimistic message in the Zustand store.

```ts
// useChat.ts — streaming hook
async function sendMessage(sessionId: string, content: string) {
  // 1. Optimistically append user message to store
  // 2. Open fetch stream to POST /v1/chat/stream
  // 3. Parse SSE deltas, accumulate into assistantMessage
  // 4. On done event, replace optimistic message with final (includes sources)
}
```

### 5.5 Theme & State

- `themeStore.ts` (Zustand) — dark/light toggle, same pattern as ai-flow-orchestrator.
- `sessionStore.ts` (Zustand) — current session ID, messages list, loading/streaming flags.
- `useInsights.ts` (react-query) — `GET /v1/insights`, 30-min stale time, manual refetch.
- `useSessions.ts` (react-query) — session list + create/delete mutations.

---

## 6. Database Schema (PostgreSQL)

```sql
-- Sessions
CREATE TABLE rag_sessions (
    id          VARCHAR PRIMARY KEY,
    title       VARCHAR(255),
    datasource  VARCHAR(100) DEFAULT 'default',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- Messages
CREATE TABLE rag_messages (
    id          VARCHAR PRIMARY KEY,
    session_id  VARCHAR REFERENCES rag_sessions(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL,  -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    sources     JSONB,                 -- [{"id": "...", "score": 0.9, "text": "..."}]
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_messages_session ON rag_messages(session_id);

-- Insights cache
CREATE TABLE rag_insights_cache (
    id           SERIAL PRIMARY KEY,
    datasource   VARCHAR(100) DEFAULT 'default',
    payload      JSONB NOT NULL,
    generated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_insights_ds ON rag_insights_cache(datasource, generated_at DESC);
```

---

## 7. Docker Compose

```yaml
# docker-compose.yml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.13.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - ES_JAVA_OPTS=-Xms512m -Xmx512m
    ports: ["9200:9200"]

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: qf
      POSTGRES_PASSWORD: qf
      POSTGRES_DB: qsint_rag
    ports: ["5432:5432"]
    volumes: [postgres-data:/var/lib/postgresql/data]

  jaeger:
    image: jaegertracing/all-in-one:1.56
    ports: ["16686:16686", "4317:4317", "4318:4318"]
    environment:
      COLLECTOR_OTLP_ENABLED: "true"

  backend:
    build: { context: ., dockerfile: Dockerfile }
    ports: ["5100:5100"]
    env_file: .env
    environment:
      DATABASE_URL: "postgresql://qf:qf@postgres:5432/qsint_rag"
      ES_HOST: "http://elasticsearch:9200"
      QSINT_OTLP_ENDPOINT: "http://jaeger:4317"
    depends_on: [elasticsearch, postgres, jaeger]

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.dev
    ports: ["5173:5173"]
    environment:
      VITE_API_BASE_URL: "http://localhost:5100"
    volumes: ["./frontend/src:/app/src"]  # hot reload

volumes:
  postgres-data: {}
```

---

## 8. Tests

### 8.1 Unit Tests (`tests/unit/`)

| File | What is tested |
|---|---|
| `test_retriever.py` | `Retriever.retrieve()` with mocked ES client and file loader; top_k slicing, score normalization |
| `test_prompt_builder.py` | Message assembly from chunks + history; XML formatting; history truncation |
| `test_insights_engine.py` | Cache hit/miss logic; JSON parsing of LLM output; TTL expiry |
| `test_session_service.py` | Create session, append messages, load history; DB operations with SQLite in-memory |

### 8.2 Integration Tests (`tests/integration/`)

| File | What is tested |
|---|---|
| `test_es_client.py` | Real ES container (testcontainers); index, index doc, search |
| `test_endpoints.py` | Flask test client; all endpoints; mock LLM responses |
| `test_session_db.py` | Real Postgres (testcontainers); session CRUD; cascade delete |

### 8.3 E2E Tests (`tests/e2e/`)

| File | What is tested |
|---|---|
| `test_chat_flow.py` | Full chat round-trip: POST /v1/chat/stream → consume SSE → verify Postgres row |
| `test_insights_flow.py` | GET /v1/insights (cold cache) → POST /v1/insights/refresh → verify updated cache |

**Test tooling:** `pytest`, `pytest-asyncio`, `testcontainers`, `responses` (HTTP mocking), `faker`.

---

## 9. Implementation Phases

### Phase 1 — Backend Skeleton (Day 1–2)
- [ ] Scaffold project layout, `requirements.txt`, `Makefile`
- [ ] `main.py` + `maps/endpoint.json` (health + stub endpoints)
- [ ] `src/config.py`
- [ ] Postgres models + `init_db()`
- [ ] `src/session/session_service.py` (CRUD)
- [ ] Docker Compose running (ES + Postgres + Jaeger + stub backend)

### Phase 2 — RAG Core (Day 3–4)
- [ ] `src/datasource/es_client.py` — connect, search, sample
- [ ] `src/datasource/file_loader.py` — JSONL/CSV/TXT ingestion + BM25 search
- [ ] `src/rag/retriever.py` — unified interface
- [ ] `src/rag/llm_client.py` — Anthropic SDK, streaming generator
- [ ] `src/rag/prompt_builder.py` — chunk formatting, history injection
- [ ] Unit tests for all three

### Phase 3 — Chat & Insights Endpoints (Day 5)
- [ ] `src/api/endpoints.py` — chat (sync + stream), session CRUD
- [ ] `src/rag/insights_engine.py` — sample + LLM analysis + Postgres cache
- [ ] `maps/endpoint.json` — all routes wired
- [ ] Integration tests for endpoints

### Phase 4 — Frontend PoC (Day 6–7)
- [ ] Vite + React + Antd scaffold (`frontend/`)
- [ ] `RagModule.tsx` + `RagShell.tsx` layout
- [ ] `InsightsPanel` + all three charts
- [ ] `NarrativeCard` + "Ask about this" hook
- [ ] `ChatPanel` with `@ant-design/x` Bubble + SSE streaming
- [ ] `SessionSidebar` + session management

### Phase 5 — Polish, Tests, Docs (Day 8)
- [ ] E2E tests
- [ ] Vite lib build config + `index.ts` exports
- [ ] `docs/architecture.md` + `docs/api_reference.md`
- [ ] `README.md` with quick-start
- [ ] `.env.example` with all variables documented

---

## 10. Key Dependencies

### Backend (`requirements.txt`)
```
# QF Framework (local wheel)
qf @ file:///path/to/dist/qf-1.0.2-py3-none-any.whl

# API / framework
flask
flask-restx
gevent
psycogreen

# Database
sqlalchemy
psycopg2-binary
alembic

# Elasticsearch
elasticsearch>=8.0.0

# LLM
anthropic>=0.30.0

# RAG / search
rank-bm25          # in-memory BM25 for file datasource

# Config
python-dotenv

# Testing
pytest
pytest-cov
testcontainers[elasticsearch,postgresql]
responses
faker
```

### Frontend (`frontend/package.json`)
```json
{
  "dependencies": {
    "antd": "^6.x",
    "@ant-design/icons": "^6.x",
    "@ant-design/plots": "^2.x",
    "@ant-design/x": "^2.x",
    "@tanstack/react-query": "^5.x",
    "zustand": "^5.x",
    "react-router-dom": "^7.x",
    "axios": "^1.x",
    "dayjs": "^1.x",
    "react-markdown": "^9.x"
  }
}
```

---

## 11. LLM Choice Rationale

**Model: `claude-sonnet-4-6`** (Anthropic)

- Best balance of intelligence, context window (200K tokens), and speed for this use case.
- Handles long RAG contexts (many retrieved chunks) without degradation.
- Native streaming support in Anthropic SDK (`stream()` context manager).
- JSON mode / structured output via `<json>` tags in system prompt for insights generation.
- Already used in the QSINT ecosystem (consistent API key management).

---

## 12. Notes & Design Decisions

1. **No Kafka** — RAG is inherently request/response. `enable_etl=False` in FrameworkSettings. The QF framework runs clean without it.

2. **SSE over WebSocket** — Simpler, works through reverse proxies without upgrade headers. Flask handles it natively with `stream_with_context`. Frontend uses `fetch` with `ReadableStream` (supports POST body, unlike native `EventSource`).

3. **Insights are LLM-generated, not computed** — Rather than running heavy NLP pipelines, we sample the corpus and ask Claude to identify patterns. This is fast to build and often produces better-quality narratives. The cache (30 min TTL) prevents over-spending on tokens.

4. **Hybrid ES search** — Default uses BM25 (`multi_match` query). If the ES index has a `vector` field, the retriever automatically switches to KNN + BM25 hybrid. Detected at startup via `get_index_stats()`.

5. **Frontend as library** — `vite.config.ts` uses `lib` mode with `external: ['react', 'antd', ...]` so the bundle is small when embedded. The standalone dev app bundles everything for local development.

6. **Session history injection** — Last 10 turns are injected into the prompt as `messages` history (Anthropic multi-turn format). This gives the LLM conversational continuity without exceeding context limits.

7. **"Ask about this" narrative hook** — Clicking a narrative card in `InsightsPanel` fires a Zustand action that sets the chat input text and switches focus to `ChatPanel`. No page navigation needed — single-page module.
