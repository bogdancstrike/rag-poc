# QSINT RAG POC 🛡️🔍

A high-performance Retrieval-Augmented Generation (RAG) Proof of Concept for intelligence analysis. This system enables analysts to query large document corpora using natural language and provides automated, AI-driven intelligence insights.

## 🚀 Features

-   **Semantic Search & RAG**: Context-aware chat using Elasticsearch and LLM integration.
-   **Multi-Task Intelligence Engine**: 
    -   **AI Summary**: Extraction of hot topics, narratives, and trends.
    -   **AI NER**: Automated Named Entity Recognition (Persons, Orgs, Locations, Tools).
    -   **AI Graph**: Detection of relationship networks between entities.
    -   **Corpus Statistics**: Real-time document distribution and timeline analytics.
-   **Asynchronous Processing**: Insights run in the background via a tasking system, allowing partial results to populate the UI as they complete.
-   **Content-Aware Caching**: SHA-256 document hashing ensures insights are only regenerated when the underlying data changes or the TTL expires.
-   **Session Management**: Persistent chat sessions stored in PostgreSQL.
-   **Real-time UI**: SSE-based streaming for chat and 5-second polling for background task progress.

## 🛠️ Tech Stack

-   **Backend**: Python (Flask / [QF Framework](https://github.com/google/gemini-cli))
-   **Frontend**: React, TypeScript, Vite, Ant Design, TailwindCSS, Recharts
-   **Vector DB / Search**: Elasticsearch 8.x (BM25 + stable random sampling)
-   **Relational DB**: PostgreSQL (Granular task state & session store)
-   **LLM Orchestration**: Ollama (Qwen 2.5 optimized)
-   **Tracing**: OpenTelemetry / Jaeger

## 📋 Prerequisites

-   **Python 3.10+**
-   **Node.js 18+**
-   **Docker & Docker Compose**
-   **Ollama** (running locally with `qwen2.5:7b` or similar)

## 🏗️ Getting Started

### 1. Environment Setup

Copy the example environment file and adjust values:
```bash
cp .env.example .env
```

### 2. Infrastructure

Spin up Elasticsearch, PostgreSQL, and Jaeger:
```bash
docker-compose up -d
```

### 3. Backend Setup

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Seed Elasticsearch with sample data
python scripts/seed_elasticsearch.py
```

### 4. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### 5. Run the Backend

```bash
# From the root directory
python3 main.py
```

## 🧠 Core Components

### Insights Tasking System
The `InsightsEngine` orchestrates multiple background threads to process different types of intelligence. It tracks task status (`pending`, `processing`, `complete`, `error`) in Postgres, enabling a responsive experience where users can see analytics while heavy LLM tasks are still running.

### Stable Sampling
Uses a fixed-seed random scoring mechanism in Elasticsearch to ensure that the document sample (and thus the analysis) remains consistent during polling, preventing redundant LLM calls.

## 🧪 Testing

```bash
# Run all tests
pytest

# Run insights engine unit tests
pytest tests/unit/test_insights_engine.py
```

---
*Developed as a POC for rapid intelligence analysis and data exploration.*
