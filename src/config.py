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
    LLM_BASE_URL    = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    LLM_MODEL       = os.getenv("LLM_MODEL", "")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    LLM_TOP_P       = float(os.getenv("LLM_TOP_P", "0.9"))
    LLM_REPETITION_PENALTY = float(os.getenv("LLM_REPETITION_PENALTY", "1.2"))
    # Hard wall-clock timeout for a single LLM API call (seconds).
    # Ollama can hang indefinitely on model load or OOM — this unblocks the worker.
    LLM_TIMEOUT     = int(os.getenv("LLM_TIMEOUT", "300"))

    # num_ctx (context window) used for chat sessions.
    # If not set in environment, LLMClient will discover it from the model.
    LLM_CHAT_CTX            = int(os.getenv("LLM_CHAT_CTX", "0"))
    # Ollama num_ctx (context window) used exclusively for insight generation.
    LLM_INSIGHTS_CTX        = int(os.getenv("LLM_INSIGHTS_CTX", "0"))
    # Max output tokens for the insights JSON response.
    LLM_INSIGHTS_MAX_TOKENS = int(os.getenv("LLM_INSIGHTS_MAX_TOKENS", "4096"))
    # Max INPUT tokens packed into insight prompts. Caps prefill time on small models.
    # 8500 tokens ≈ 29 750 chars: ~20 docs for simple tasks, ~14 for relationship_network.
    # Values below ~7 000 cause Ollama KV-cache bimodal spikes (26s/53s alternating).
    LLM_INSIGHTS_INPUT_MAX_TOKENS = int(os.getenv("LLM_INSIGHTS_INPUT_MAX_TOKENS", "8500"))
    # Conservative chars-per-token estimate.
    LLM_CHARS_PER_TOKEN     = float(os.getenv("LLM_CHARS_PER_TOKEN", "3.5"))
    # Characters reserved for prompts and JSON schema.
    LLM_INSIGHTS_RESERVE_CHARS = int(os.getenv("LLM_INSIGHTS_RESERVE_CHARS", "10000"))

    # Enrichment (per-document) JSON context — smaller is fine, only one doc at a time.
    LLM_JSON_MAX_TOKENS = int(os.getenv("LLM_JSON_MAX_TOKENS", "16384"))

    # Candidate pool fetched from ES before relevance filtering.
    # Larger pool = better chance of finding truly relevant docs.
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "50"))
    # Relative relevance threshold: keep a doc only if its BM25 score is at
    # least this fraction of the top-scoring result (0.35 = 35%).
    # Adapts automatically to query difficulty — no fixed absolute floor needed.
    RAG_RELATIVE_THRESHOLD = float(os.getenv("RAG_RELATIVE_THRESHOLD", "0.35"))
    # Hard cap on chunks passed to the LLM. Fewer, highly-relevant chunks
    # produce better answers than many marginally-relevant ones.
    RAG_MAX_CONTEXT_CHUNKS = int(os.getenv("RAG_MAX_CONTEXT_CHUNKS", "8"))
    # Max conversation history turns injected into prompt
    HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "10"))

    # ── Insights ───────────────────────────────────────────────────────────────
    INSIGHTS_CACHE_TTL = int(os.getenv("INSIGHTS_CACHE_TTL", "1800"))  # seconds
    # Candidate pool sampled from the index before budget-aware packing.
    # The prompt builder will pack as many as fit within LLM_INSIGHTS_CTX;
    # extras are silently dropped. Larger pool = more representative sample.
    INSIGHTS_MAX_DOCS  = int(os.getenv("INSIGHTS_MAX_DOCS", "2000"))
    # Hard cap for per-document enrichment (full-text, single doc at a time).
    INSIGHTS_MAX_DOCS_FULL_TEXT = int(os.getenv("INSIGHTS_MAX_DOCS_FULL_TEXT", "40"))

    # ── Embeddings (fastembed / bge-m3, CPU-only) ─────────────────────────────────
    EMBED_MODEL      = os.getenv("EMBED_MODEL",      "BAAI/bge-large-en-v1.5")
    EMBED_CACHE_DIR  = os.getenv("EMBED_CACHE_DIR",  "./data/embed_cache")
    EMBED_DIMS       = int(os.getenv("EMBED_DIMS",   "1024"))
    EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))
    # When set, the EmbeddingClient POSTs to a TEI GPU server (HTTP). Leave
    # empty to fall back to the in-process CPU fastembed path — useful for
    # tests, offline dev, or boxes without an embedding service.
    EMBED_BASE_URL   = os.getenv("EMBED_BASE_URL", "").rstrip("/")
    EMBED_TIMEOUT    = int(os.getenv("EMBED_TIMEOUT", "60"))

    # ── Kafka / Worker (required by QF framework at import time — unused for RAG) ──
    WORKER_NAME              = os.getenv("WORKER_NAME", "qsint-rag")
    KAFKA_BOOTSTRAP_SERVERS  = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_POLL_TIMEOUT_MS    = int(os.getenv("KAFKA_POLL_TIMEOUT_MS", "1"))
    KAFKA_POLL_MAX_RECORDS   = int(os.getenv("KAFKA_POLL_MAX_RECORDS", "200"))
    KAFKA_IDLE_SLEEP_SEC     = float(os.getenv("KAFKA_IDLE_SLEEP_SEC", "0"))
    KAFKA_COMMIT_TICK_SEC    = float(os.getenv("KAFKA_COMMIT_TICK_SEC", "0.2"))
    KAFKA_MAX_JOBS_PER_TP_PER_TICK = int(os.getenv("KAFKA_MAX_JOBS_PER_TP_PER_TICK", "20"))
    KAFKA_COMMIT_STRATEGY    = os.getenv("KAFKA_COMMIT_STRATEGY", "before")

    # New: RAG-specific Kafka topics
    KAFKA_TOPIC_LLM_TASKS  = os.getenv("KAFKA_TOPIC_LLM_TASKS",  "qsint.rag.llm_tasks")
    KAFKA_TOPIC_FAST_TASKS = os.getenv("KAFKA_TOPIC_FAST_TASKS", "qsint.rag.fast_tasks")
    KAFKA_CONSUMER_GROUP   = os.getenv("KAFKA_CONSUMER_GROUP",   "qsint-rag-worker")

    # LLM concurrency: 1=sequential, N=up to N parallel LLM calls via Kafka worker
    LLM_PARALLEL = int(os.getenv("LLM_PARALLEL", "1"))

    # ── Redis (required by QF framework at import time — not used for RAG) ────
    REDIS_HOST            = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT            = os.getenv("REDIS_PORT", "6379")
    REDIS_DB              = os.getenv("REDIS_DB", "0")
    REDIS_MAX_CONNECTIONS = os.getenv("REDIS_MAX_CONNECTIONS", "50")
    REDIS_SOCKET_TIMEOUT  = os.getenv("REDIS_SOCKET_TIMEOUT", "5.0")
    REDIS_CONNECT_TIMEOUT = os.getenv("REDIS_CONNECT_TIMEOUT", "5.0")
    REDIS_RETRY_ON_TIMEOUT= os.getenv("REDIS_RETRY_ON_TIMEOUT", "true")

    # ── LLM serving runtime (vLLM-side knobs surfaced in the UI) ──────────────
    # These shadow the values vLLM is launched with via docker-compose-llm.yml,
    # so the backend can report concurrency limits etc. without scraping
    # vLLM-internal HTTP endpoints that don't exist (vLLM has no
    # /get_server_info — only /metrics + /v1/models).
    VLLM_MAX_NUM_SEQS = int(os.getenv("VLLM_MAX_NUM_SEQS", "16"))

    # ── File ingestion (user-uploaded files into investigations) ──────────────
    # Root directory for original-file storage. Each upload lives at
    # ${UPLOADS_DIR}/<investigation_id>/<file_id>/{original.<ext>, meta.json}.
    UPLOADS_DIR             = os.getenv("UPLOADS_DIR", "./data/uploads")
    # Hard cap per file. 0 = unlimited (the OS / disk imposes the real ceiling).
    UPLOADS_MAX_SIZE_BYTES  = int(os.getenv("UPLOADS_MAX_SIZE_BYTES", str(5 * 1024 * 1024 * 1024)))
    # ES bulk-index batch size during streaming ingestion.
    INGEST_BATCH_SIZE       = int(os.getenv("INGEST_BATCH_SIZE", "500"))
    # Per-record character cap for the ES `text` field. Prevents one huge cell
    # from blowing up indexing or downstream LLM enrichment.
    INGEST_TEXT_TRUNCATE    = int(os.getenv("INGEST_TEXT_TRUNCATE", "20000"))
    # Number of sample records sent to the LLM for column→field mapping inference.
    INGEST_SAMPLE_RECORDS   = int(os.getenv("INGEST_SAMPLE_RECORDS", "5"))
    # Anti-zip-bomb caps (Phase 3 archive handler — reserved here so they're
    # discoverable even though the handler ships later).
    INGEST_ARCHIVE_MAX_DEPTH       = int(os.getenv("INGEST_ARCHIVE_MAX_DEPTH", "2"))
    INGEST_ARCHIVE_EXPANSION_RATIO = int(os.getenv("INGEST_ARCHIVE_EXPANSION_RATIO", "20"))

    # ── Tracing ────────────────────────────────────────────────────────────────
    ENABLE_TRACING = os.getenv("ENABLE_TRACING", "false").lower() in ("1", "true", "yes")
    OTLP_ENDPOINT  = os.getenv("QSINT_OTLP_ENDPOINT", "http://localhost:4317")

    logger.setLevel(LOG_LEVEL)
