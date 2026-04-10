# Implementation Plan: Multi-Index Exploration & AI Mode

## 1. Immediate Fix: LLM JSON Schema Compliance
- **Issue**: Smaller LLMs (like Qwen 2.5 7b) tend to "forget" the JSON schema if it is placed before a massive context block.
- **Action**: Update `src/rag/prompt_builder.py` to place the `REQUIRED SCHEMA` instructions *after* the document texts in the user prompt. This ensures the schema is the last thing the LLM sees before generating.

## 2. Infrastructure & Data Seeding
- **Goal**: Provide at least 5 distinct Elasticsearch indices.
- **Action**: Update `scripts/seed_elasticsearch.py` to generate documents for 5 different categories (e.g., `qsint_docs_global`, `qsint_docs_europe`, `qsint_docs_apac`, `qsint_docs_cyber`, `qsint_docs_finance`).
- **Action**: Adjust `ESClient` in `src/datasource/es_client.py` to accept dynamic index names and list available indices (`qsint_docs_*`).

## 3. Backend API Enhancements
- **Goal**: Support dynamic index selection and raw data exploration.
- **Action**: Add `GET /v1/datasource/indices` endpoint to list available indices.
- **Action**: Add `GET /v1/documents` endpoint to support tabular exploration (pagination, basic search).
- **Action**: Update all RAG and Insights endpoints to dynamically use the requested `datasource` as the Elasticsearch index. Update `Retriever` and `ESClient` accordingly.

## 4. Frontend UI Reimagine
- **Goal**: Separate raw data exploration from AI analysis for better UX.
- **Action**: Implement a **Sidebar** for index selection.
- **Action**: Implement a **Tabular Data View** as the default state for the selected index (using Ant Design's `Table`).
- **Action**: Add an **"Analyze with AI"** button. Clicking this transitions the UI into the RAG Chat and Insights Dashboard mode for that specific index.
- **Action**: Create new hooks (`useIndices`, `useDocuments`) to support the new features.

## 5. Testing & Validation
- **Action**: Update existing unit tests in `tests/unit/` to pass dynamic index names.
- **Action**: Add new tests for the `GET /v1/documents` and `GET /v1/datasource/indices` endpoints.
- **Action**: Run `pytest` to verify all components work correctly.
