"""Application configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

from framework.commons.logger import logger


class Config:
    # ── Application ────────────────────────────────────────────────────────────
    API_PORT   = int(os.getenv("API_PORT", "5100"))
    DEV_MODE   = os.getenv("DEV_MODE", "true").lower() in ("1", "true", "yes")
    LOG_LEVEL  = os.getenv("LOG_LEVEL", "DEBUG")

    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://qf:qf@localhost:5432/qsint_rag")

    # ── Elasticsearch ──────────────────────────────────────────────────────────
    ES_HOST     = os.getenv("ES_HOST", "http://localhost:9200")
    ES_INDEX    = os.getenv("ES_INDEX", "qsint_docs")
    ES_USER     = os.getenv("ES_USER", "")
    ES_PASSWORD = os.getenv("ES_PASSWORD", "")

    # ── Datasource ─────────────────────────────────────────────────────────────
    # "es" = Elasticsearch index, "file" = local JSONL/CSV/TXT file
    DATASOURCE_TYPE      = os.getenv("DATASOURCE_TYPE", "es")
    FILE_DATASOURCE_PATH = os.getenv("FILE_DATASOURCE_PATH", "./data/corpus.jsonl")

    # ── LLM (Ollama OpenAI-compatible API) ─────────────────────────────────────
    LLM_BASE_URL   = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    LLM_MODEL      = os.getenv("LLM_MODEL", "qwen2.5:7b")
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

    # Number of document chunks to retrieve per query (upper bound)
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "20"))
    # Minimum relevance score — chunks below this threshold are discarded.
    # Set to 0.0 to disable filtering (keep all retrieved chunks).
    RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.15"))
    # Max chunks passed to the LLM after score filtering
    RAG_MAX_CONTEXT_CHUNKS = int(os.getenv("RAG_MAX_CONTEXT_CHUNKS", "20"))
    # Max conversation history turns injected into prompt
    HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "10"))

    # ── Insights ───────────────────────────────────────────────────────────────
    INSIGHTS_CACHE_TTL = int(os.getenv("INSIGHTS_CACHE_TTL", "1800"))  # seconds
    # How many docs to sample for AI analysis. Titles+topics only are sent to the
    # LLM so a large sample fits comfortably within the context window.
    INSIGHTS_MAX_DOCS  = int(os.getenv("INSIGHTS_MAX_DOCS", "500"))
    # Hard cap used only when full text is needed (enrichment etc.)
    INSIGHTS_MAX_DOCS_FULL_TEXT = int(os.getenv("INSIGHTS_MAX_DOCS_FULL_TEXT", "40"))

    # ── Kafka / Worker (required by QF framework at import time — unused for RAG) ──
    WORKER_NAME              = os.getenv("WORKER_NAME", "qsint-rag")
    KAFKA_BOOTSTRAP_SERVERS  = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_POLL_TIMEOUT_MS    = int(os.getenv("KAFKA_POLL_TIMEOUT_MS", "1"))
    KAFKA_POLL_MAX_RECORDS   = int(os.getenv("KAFKA_POLL_MAX_RECORDS", "200"))
    KAFKA_IDLE_SLEEP_SEC     = float(os.getenv("KAFKA_IDLE_SLEEP_SEC", "0"))
    KAFKA_COMMIT_TICK_SEC    = float(os.getenv("KAFKA_COMMIT_TICK_SEC", "0.2"))
    KAFKA_MAX_JOBS_PER_TP_PER_TICK = int(os.getenv("KAFKA_MAX_JOBS_PER_TP_PER_TICK", "20"))
    KAFKA_COMMIT_STRATEGY    = os.getenv("KAFKA_COMMIT_STRATEGY", "before")

    # ── Redis (required by QF framework at import time — not used for RAG) ────
    REDIS_HOST            = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT            = os.getenv("REDIS_PORT", "6379")
    REDIS_DB              = os.getenv("REDIS_DB", "0")
    REDIS_MAX_CONNECTIONS = os.getenv("REDIS_MAX_CONNECTIONS", "50")
    REDIS_SOCKET_TIMEOUT  = os.getenv("REDIS_SOCKET_TIMEOUT", "5.0")
    REDIS_CONNECT_TIMEOUT = os.getenv("REDIS_CONNECT_TIMEOUT", "5.0")
    REDIS_RETRY_ON_TIMEOUT= os.getenv("REDIS_RETRY_ON_TIMEOUT", "true")

    # ── Tracing ────────────────────────────────────────────────────────────────
    ENABLE_TRACING = os.getenv("ENABLE_TRACING", "false").lower() in ("1", "true", "yes")
    OTLP_ENDPOINT  = os.getenv("QSINT_OTLP_ENDPOINT", "http://localhost:4317")

    logger.setLevel(LOG_LEVEL)
