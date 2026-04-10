# Implementation Plan: QSINT RAG — Feature Expansion & UX Improvements

## Bug Fix 1: Graph JSON Parse Failure
- **Issue**: `_parse_json` fails on valid-looking JSON output from the graph LLM task.
  - Root cause 1: `re.sub(r",\s*}", "}", ...)` only fixes trailing commas before `}`, not before `]`.
  - Root cause 2: `re.sub(r"//.*", "", ...)` corrupts JSON strings containing `://` (URLs).
  - Root cause 3: `rfind("}")` finds wrong closing brace if extra text follows the JSON object.
  - Root cause 4: Graph prompt instructs LLM to use `"id": "string"`, causing it to emit actual Elasticsearch UUID doc-IDs as node IDs, leading to a very large graph JSON that can exceed context or include unexpected formatting.
- **Fix**:
  - Rewrite `InsightsEngine._parse_json` with a proper brace-matching extractor (tracks `in_string` + `escape_next` state) so the last `}` is always the true structural close.
  - Replace the `//.*` comment removal with a URL-safe version that skips lines containing `://`.
  - Handle trailing commas before both `}` and `]`.
  - Update `INSIGHTS_GRAPH_PROMPT` to instruct the LLM to use entity names (not doc IDs) as node IDs, limit to 10–15 nodes and 15–25 edges.

## Bug Fix 2: Async Insights / Enrichment (Timeout Fix)
- **Issue**: `GET /v1/insights` blocks the HTTP thread while `retriever.get_sample()` queries Elasticsearch (can take >60 s). Similarly, `POST /v1/documents/enrich` blocks while the LLM runs.
- **Fix**:
  - `get_insights()`: immediately mark all tasks as `"pending"` in Postgres, then submit a lightweight coordinator to the background thread pool that fetches the sample and triggers AI tasks. Return `current_insights` immediately (HTTP responds in <100 ms).
  - `document_enrichment_handler`: if a complete/cached row exists return it; otherwise create `"pending"` row, submit a background worker, return 202. Frontend already polls via `refetchInterval`.
  - Add `POST /v1/documents/enrich/field` for per-operation enrichment reload (sentiment / classification / entities / summary independently).

## Feature 1: SSE Push for Insights
- **Goal**: Replace frontend polling for insights with server-sent events so the browser receives updates the moment each background task completes.
- **Action**:
  - Add `InsightsEventBus` singleton in `insights_engine.py` (thread-safe subscriber list per datasource).
  - Call `event_bus.publish()` inside `_set_task_status()` after every DB write.
  - Add `GET /v1/insights/stream?datasource=<ds>` endpoint that subscribes to the bus and streams SSE events (`state`, `task_update`, heartbeat comments).
  - Frontend: add `useInsightsStream` hook that opens the SSE connection and updates React Query cache on each event. Falls back to polling if SSE fails.

## Feature 2: Document Expansion — Split Panel
- **Goal**: When a user expands a document row in Data Exploration, the page splits: left = table, right = detail panel.
- **Action**:
  - Refactor `DataTable.tsx` to maintain `expandedDoc: Document | null` state.
  - When a row is expanded, render a right-hand panel (`DocumentDetailPanel`) using Ant Design's split layout (table at 55%, panel at 45%).
  - Panel sections: **Full Document Content** (scrollable), **AI Enrichment** (separate card, marked "ENRICHMENT").
  - Per-enrichment-operation reload buttons: each field (Summary, Sentiment, Classification, Entities) has a "Reload" button that calls `POST /v1/documents/enrich/field`.
  - "Close" button collapses the panel and restores the full table width.

## Feature 3: Platform Overview — Task Control & Detail Page
- **Goal**: Restart/stop tasks from Platform Overview; click a task to see its full detail.
- **Action**:
  - Add `POST /v1/dashboard/tasks/restart` endpoint that handles both insight-type and enrichment-type tasks.
  - Add `DELETE /v1/dashboard/tasks` endpoint to clear a specific task record.
  - `OverviewDashboard`: add **Restart** and **Clear** action buttons per row; clicking a row navigates to the task detail view.
  - Add `TaskDetailPanel.tsx` component showing: task ID, datasource, type, status, timestamps (local), duration, input (sample docs / doc content), output (payload JSON), error trace.
  - `RagModule.tsx`: add lightweight state-based router — `activePage: 'main' | 'task'` with `selectedTask` state; `window.history.pushState` for shareable URLs (`#/tasks/<id>`).

## Feature 4: Local Time Conversion
- **Goal**: All timestamps stored in UTC in Postgres must display in the user's local timezone in the UI.
- **Action**:
  - Add `dayjs` UTC plugin (`dayjs/plugin/utc`) and configure it globally.
  - Ensure backend always emits ISO-8601 strings with `+00:00` offset (already done via `datetime.now(timezone.utc).isoformat()`).
  - In frontend, replace all `dayjs(val).format(...)` with `dayjs.utc(val).local().format(...)`.
  - Add a `<Tooltip title={utcString}>` wrapper so users can hover to see raw UTC value.

## Feature 5: Send to RAG from Intelligence Reports
- **Goal**: Users can send intelligence data from the Insights panel directly to the RAG Chat.
- **Action**:
  - Add a **"Send to RAG"** button in `InsightsPanel` header that composes a context message from the current insights (hot topics, narratives, entities) and sends it to the Chat tab.
  - Add a **"Send selected docs to RAG"** option on individual narrative / entity cards via the existing `onAskAbout` callback.
  - Add a **Data Table** tab inside `InsightsPanel` (alongside Intelligence Report and Chat) to show raw underlying documents from the selected datasource.

## Feature 6: UI / UX Improvements
- **Goal**: Cleaner, more professional interface.
- **Action**:
  - Consistent card shadows, spacing tokens, and Ant Design `colorBgElevated` backgrounds.
  - Status badges with animated spinners for processing tasks.
  - Timestamp tooltips showing UTC alongside local time everywhere.
  - Empty-state illustrations for each panel.
  - Progress bars on the Platform Overview showing task completion rate.
  - Better error display with `<Alert>` and retry actions.
  - Collapsed sidebar for mobile-friendly layout.

## Feature 7: Comprehensive README.md
- **Goal**: Full technical documentation for engineers and analysts.
- **Action**:
  - Project overview, tech stack, architecture diagram (mermaid flowchart).
  - Sequence diagrams for: RAG Chat (SSE), Insights generation, Document enrichment.
  - Component breakdown (backend modules + frontend components).
  - REST API reference table.
  - Setup & configuration guide (.env variables).
  - Feature examples with screenshots descriptions.

## Implementation Order
1. Bug Fix 1 — `_parse_json` + graph prompt
2. Bug Fix 2 — async insights + async enrichment  
3. Backend: SSE insights stream + event bus
4. Backend: task control endpoints + enrichment field endpoint
5. Backend: register all new routes in `endpoint.json`
6. Frontend: split-panel DataTable with per-field reload
7. Frontend: OverviewDashboard task control + TaskDetailPanel
8. Frontend: InsightsPanel "Send to RAG" + data table tab
9. Frontend: SSE insights hook
10. Frontend: RagModule routing for task detail
11. Frontend: local time formatting everywhere
12. README.md
