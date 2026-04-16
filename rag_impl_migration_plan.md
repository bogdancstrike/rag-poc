# RAG Migration Plan: BM25 → Hybrid BM25 + Semantic Search

**Date:** 2026-04-16  
**Scope:** Embeddings at investigation ingest, hybrid chat retrieval, semantic insight sampling  
**Constraint:** RTX 3080 10 GB — GPU stays owned by Qwen3-4B-AWQ (LLM). Embeddings run CPU-only.

---

## Embedding Model Choice

**`BAAI/bge-m3`** via `fastembed` (CPU).

- 1024-dim, 100+ languages — required for multilingual OSINT (Arabic, Russian, French, mixed)
- ~570 MB RAM, ~3 s/batch of 64 docs on a modern CPU
- No second GPU service needed; `fastembed` runs ONNX on CPU, completely decoupled from SGLang
- Downloaded once to `./data/embed_cache` on first use; subsequent deploys are instant
- Alternative `bge-small-en-v1.5` (384-dim, English-only) explicitly rejected — degrades silently on non-English intel docs

---

## Architecture Overview

```
Investigation Created
        │
        ▼
handle_create_investigation()
  ├── create_index()           ← mapping now includes embedding: dense_vector(1024)
  ├── copy_documents()         ← scroll+bulk copy from source indices (unchanged)
  ├── status → "ready"         ← chat + BM25 search work immediately
  └── publish embed_docs task
              │
              ▼ (Kafka LLM topic — CPU-gated)
        handle_embed_docs()
          ├── scroll investigation index (batch_size=64)
          ├── EmbeddingClient.embed(texts) via fastembed/bge-m3
          ├── bulk update docs with embedding field
          ├── invalidate_vector_cache(index_name)
          └── status → "ready_with_vectors"

Chat Query                     Insight Task
     │                               │
     ▼                               ▼
retriever.retrieve()    retriever.get_semantic_sample(insight_type)
     │                               │
     ▼                               ▼
es_client.search()      es_client.get_semantic_sample()
  ├── _check_vector_field()    ├── KNN with topic-anchored query vectors
  │     ├── True  → _hybrid_search() (RRF: BM25 + KNN)
  │     └── False → _keyword_search() (BM25 fallback)
  └── normalise_hits()         └── pad with random_score if anchors return too few
```

---

## Phase 1 — Infrastructure: EmbeddingClient

**New file:** `src/datasource/embedding_client.py`

```python
class EmbeddingClient:
    def __init__(self):
        self._model = None   # lazy-loaded on first embed() call

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(
                model_name=Config.EMBED_MODEL,
                cache_dir=Config.EMBED_CACHE_DIR,
            )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        truncated = [t[:2000] for t in texts]   # ~512 tokens; captures full semantic signal
        return [v.tolist() for v in self._get_model().embed(truncated)]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


_client: EmbeddingClient | None = None

def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
```

**`requirements.txt`** — add:
```
fastembed>=0.3.0
```

---

## Phase 2 — Index Mapping: Add `dense_vector` Field

**File:** `src/datasource/es_client.py`

### `create_index()` — extend default mapping

Add to the `"properties"` dict:

```python
"embedding": {
    "type":       "dense_vector",
    "dims":       Config.EMBED_DIMS,   # 1024
    "index":      True,
    "similarity": "cosine",
},
```

New investigation indices get this field at creation. Existing source indices (`qsint_docs*`) keep BM25 only — hybrid activates per-index via detection.

### `_check_vector_field()` — tighten detection

```python
has_vector = props.get("embedding", {}).get("type") == "dense_vector"
```

### Add `invalidate_vector_cache()`

```python
def invalidate_vector_cache(self, index_name: str) -> None:
    """Clear cached detection so hybrid search activates after embed_docs completes."""
    self._has_vector_cache.pop(index_name, None)
```

---

## Phase 3 — Hybrid Search: Implement `_hybrid_search()` with ES RRF

**File:** `src/datasource/es_client.py` — replace stub at line 155

ES 8.13 native RRF (`rank.rrf`) — no score normalization needed, no weight tuning.

```python
def _hybrid_search(self, query: str, top_k: int, index_name: str) -> list[dict]:
    from src.datasource.embedding_client import get_embedding_client
    q = query[:self._MAX_QUERY_LEN]

    try:
        query_vec = get_embedding_client().embed_one(q)
    except Exception as e:
        logger.warning(f"[es] embed failed, falling back to BM25: {e}")
        return self._keyword_search(query, top_k, index_name)

    rank_window = top_k * 3   # RRF needs more candidates than final top_k

    try:
        resp = self._client.search(
            index=index_name,
            body={
                "size": top_k,
                "rank": {
                    "rrf": {
                        "rank_window_size": rank_window,
                        "rank_constant":    60,
                    }
                },
                "query": {
                    "bool": {
                        "should": [
                            {
                                "multi_match": {
                                    "query":                 q,
                                    "fields":               ["text^2", "title^4", "content^2"],
                                    "type":                 "best_fields",
                                    "minimum_should_match": "30%",
                                }
                            },
                            {
                                "multi_match": {
                                    "query":  q,
                                    "fields": ["text^2", "title^4"],
                                    "type":   "phrase",
                                    "boost":  3.0,
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "knn": {
                    "field":          "embedding",
                    "query_vector":   query_vec,
                    "k":              rank_window,
                    "num_candidates": rank_window * 2,
                },
                "_source": True,
            },
        )
        return self._normalise_hits(resp["hits"]["hits"])
    except Exception as e:
        logger.error(f"[es] hybrid search error, falling back to BM25: {e}")
        return self._keyword_search(query, top_k, index_name)
```

**Fallback chain:** embed query → if fails → BM25. Hybrid query → if ES error → BM25.  
`rank_constant=60` is the ES default; do not tune without labeled relevance judgments.

---

## Phase 4 — Embedding Ingest: `embed_docs` Kafka Task

### 4a. Task handler — `src/worker/task_handlers.py`

Add to `dispatch_task()` routing:
```python
elif ttype == "embed_docs":
    handle_embed_docs(task)
```

New handler:

```python
def handle_embed_docs(task: dict) -> None:
    """
    Embed all docs in an investigation index in batches, then activate hybrid search.

    Task shape:
        {
            "task_type":        "embed_docs",
            "investigation_id": str,
            "index_name":       str,
        }

    Flow:
        scroll index (text + title fields only)
        → batch embed via EmbeddingClient
        → bulk update each doc with embedding field
        → invalidate_vector_cache so hybrid search activates on next query
        → update investigation status to "ready_with_vectors"
    """
    from elasticsearch import helpers as es_helpers
    from src.datasource.es_client import ESClient
    from src.datasource.embedding_client import get_embedding_client
    from src.session.session_service import update_investigation_status

    inv_id     = task["investigation_id"]
    index_name = task["index_name"]
    batch_size = Config.EMBED_BATCH_SIZE   # default 64

    es       = ESClient()
    embedder = get_embedding_client()

    total = 0
    resp      = es._client.search(
        index=index_name,
        body={
            "size":    batch_size,
            "_source": ["text", "title", "content", "body", "description"],
        },
        scroll="5m",
    )
    scroll_id = resp.get("_scroll_id")

    try:
        while True:
            hits = resp["hits"]["hits"]
            if not hits:
                break

            doc_ids = [h["_id"] for h in hits]
            texts = []
            for h in hits:
                src   = h.get("_source", {})
                body  = src.get("text") or src.get("content") or src.get("body") or ""
                title = src.get("title") or ""
                texts.append(f"{title}\n{body}" if title else body)

            vectors = embedder.embed(texts)

            actions = [
                {
                    "_op_type": "update",
                    "_index":   index_name,
                    "_id":      doc_id,
                    "doc":      {"embedding": vec},
                }
                for doc_id, vec in zip(doc_ids, vectors)
            ]
            ok, _ = es_helpers.bulk(es._client, actions, raise_on_error=False)
            total += ok
            logger.info(f"[embed_docs] {total} docs embedded in {index_name}")

            resp = es._client.scroll(scroll_id=scroll_id, scroll="5m")
            scroll_id = resp.get("_scroll_id")
    finally:
        if scroll_id:
            try:
                es._client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass

    es._client.indices.refresh(index=index_name)
    es.invalidate_vector_cache(index_name)

    logger.info(f"[embed_docs] Complete: {total} docs in {index_name}", "magenta")
    update_investigation_status(
        investigation_id=inv_id,
        status="ready_with_vectors",
        doc_count=total,
    )
```

### 4b. Wire into `handle_create_investigation()`

After the existing `update_investigation_status(status="ready", ...)` call:

```python
if total_copied > 0:
    from src.worker.kafka_producer import publish_task
    publish_task({
        "task_type":        "embed_docs",
        "investigation_id": inv_id,
        "index_name":       index_name,
    })
    logger.info(f"[investigation] embed_docs queued for {index_name}")
```

**Status lifecycle:** `creating → ready → (background) → ready_with_vectors`  
The `ready` status means BM25 search and chat work immediately. Hybrid activates silently when embedding finishes.

### 4c. Kafka routing — `src/worker/kafka_producer.py`

Route `embed_docs` to the LLM topic (CPU-gated, semaphore-limited):

```python
llm_types = {"insight_ai", "enrich_doc", "enrich_field", "embed_docs"}
topic = Config.KAFKA_TOPIC_LLM_TASKS if task.get("task_type") in llm_types \
        else Config.KAFKA_TOPIC_FAST_TASKS
```

This prevents CPU+GPU contention: embedding and LLM tasks never run concurrently.

### 4d. Kafka consumer — `src/worker/kafka_consumer.py`

Add `"embed_docs"` to `_LLM_TYPES` set so it gets watchdog timeout treatment:
```python
_LLM_TYPES = {"insight_ai", "enrich_doc", "enrich_field", "embed_docs"}
```

---

## Phase 5 — Semantic Sampling for Insights

Currently all insight types (trending_signals, active_narratives, etc.) use `random_score` sampling — topic-blind. With embeddings, each insight type retrieves docs semantically relevant to its purpose.

### 5a. Anchor queries per insight type

**File:** `src/datasource/es_client.py` — add class-level constant:

```python
_INSIGHT_ANCHORS: dict[str, list[str]] = {
    "trending_signals": [
        "emerging threat actor new attack campaign",
        "sudden increase activity escalation alert",
        "breaking development rapid change",
    ],
    "active_narratives": [
        "propaganda disinformation narrative campaign message",
        "coordinated information operation influence",
        "political framing media discourse storyline",
    ],
    "hot_topics_sentiment": [
        "sentiment opinion attitude hostility anger",
        "positive negative reaction criticism support",
        "controversy debate polarization conflict",
    ],
    "relationship_network": [
        "entity organization actor connection network affiliation",
        "collaboration cooperation partnership agreement",
        "command structure hierarchy chain leadership",
    ],
    # corpus_statistics, top_regions, top_entities, top_platforms
    # → use existing aggregations path, no semantic sampling needed
}
```

### 5b. `get_semantic_sample()` in `ESClient`

```python
def get_semantic_sample(self, n: int, index_name: str, insight_type: str) -> list[dict]:
    """Semantically anchored doc sample for a given insight type.

    Falls back to get_sample_docs() (random_score) when:
    - index has no dense_vector field (pre-embedding investigation)
    - insight_type has no defined anchors (stats tasks)
    - KNN query fails
    """
    idx = index_name or self._default_index

    if not self._check_vector_field(idx):
        return self.get_sample_docs(n, idx)

    anchors = self._INSIGHT_ANCHORS.get(insight_type)
    if not anchors:
        return self.get_sample_docs(n, idx)

    from src.datasource.embedding_client import get_embedding_client
    embedder  = get_embedding_client()
    k_per     = max(10, n // len(anchors))
    raw_hits: list[dict] = []
    seen_ids: set[str]   = set()

    for anchor in anchors:
        try:
            vec  = embedder.embed_one(anchor)
            resp = self._client.search(
                index=idx,
                body={
                    "size": k_per,
                    "knn":  {
                        "field":          "embedding",
                        "query_vector":   vec,
                        "k":              k_per,
                        "num_candidates": k_per * 2,
                    },
                    "_source": True,
                },
            )
            for hit in resp["hits"]["hits"]:
                if hit["_id"] not in seen_ids:
                    seen_ids.add(hit["_id"])
                    raw_hits.append(hit)
        except Exception as e:
            logger.warning(f"[es] semantic anchor failed ({anchor[:40]}): {e}")

    # Pad with random docs if anchors returned too few
    if len(raw_hits) < n:
        pad_resp = self._client.search(
            index=idx,
            body={
                "size":  n - len(raw_hits),
                "query": {
                    "function_score": {
                        "functions":  [{"random_score": {"seed": 12, "field": "_seq_no"}}],
                        "boost_mode": "replace",
                    }
                },
                "_source": True,
            },
        )
        for hit in pad_resp["hits"]["hits"]:
            if hit["_id"] not in seen_ids:
                seen_ids.add(hit["_id"])
                raw_hits.append(hit)

    logger.info(f"[es] semantic_sample: {len(raw_hits[:n])} docs for {insight_type} in {idx}")
    return self._normalise_hits(raw_hits[:n])
```

### 5c. `get_semantic_sample()` in `Retriever`

**File:** `src/rag/retriever.py`

```python
def get_semantic_sample(
    self, n: int = None, index_name: str = None, insight_type: str = "trending_signals"
) -> list[dict]:
    count = n or Config.INSIGHTS_MAX_DOCS
    try:
        if self._es_client:
            return self._es_client.get_semantic_sample(count, index_name, insight_type)
        if self._file_loader:
            return self._file_loader.get_sample(count)
    except Exception as e:
        logger.error(f"[retriever] get_semantic_sample error: {e}", exc_info=True)
    return self.get_sample(count, index_name)
```

### 5d. Wire into `handle_insight_ai()`

**File:** `src/worker/task_handlers.py`

Replace `retriever.get_sample()` with `retriever.get_semantic_sample()`:

```python
def handle_insight_ai(task: dict) -> None:
    datasource   = task["datasource"]
    insight_type = task["insight_type"]
    sample_hash  = task["sample_hash"]

    from src.rag.insights_engine import get_insights_engine
    from src.rag.retriever import get_retriever

    engine    = get_insights_engine()
    retriever = get_retriever()

    # Semantic sample anchored to this insight type (falls back to random if no vectors)
    sample = retriever.get_semantic_sample(
        n=Config.INSIGHTS_MAX_DOCS,
        index_name=datasource,
        insight_type=insight_type,
    )

    engine._run_ai_task(datasource, insight_type, sample, sample_hash)
```

`sample_hash` is still computed by the coordinator from a random sample — it acts as a corpus fingerprint for cache invalidation, not as a sample fingerprint. Stats tasks (`handle_insight_stats`) are unchanged — they use ES aggregations.

---

## Phase 6 — Config Additions

**File:** `src/config.py`

```python
# ── Embeddings ─────────────────────────────────────────────────────────────────
EMBED_MODEL      = os.getenv("EMBED_MODEL",      "BAAI/bge-m3")
EMBED_CACHE_DIR  = os.getenv("EMBED_CACHE_DIR",  "./data/embed_cache")
EMBED_DIMS       = int(os.getenv("EMBED_DIMS",   "1024"))
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))
EMBED_THREADS    = int(os.getenv("EMBED_THREADS", "4"))
```

**`.env` / `.env.example`** — add:
```
EMBED_MODEL=BAAI/bge-m3
EMBED_CACHE_DIR=./data/embed_cache
EMBED_DIMS=1024
EMBED_BATCH_SIZE=64
EMBED_THREADS=4
```

**`docker-compose.yml`** — add a volume for the embed cache so it survives redeployments:
```yaml
volumes:
  embed-cache: {}

services:
  # (backend or wherever the worker runs)
  # mount: embed-cache:/app/data/embed_cache
```

---

## Fallback Matrix

| Scenario | `_check_vector_field()` | Chat search | Insights sampling |
|---|---|---|---|
| Old source index (`qsint_docs*`) | `False` | BM25 | random_score |
| New investigation, embedding pending | `False` | BM25 | random_score |
| New investigation, embedding complete | `True` | BM25 + KNN (RRF) | semantic anchors |
| Embedding model unavailable | n/a | BM25 (fallback in `_hybrid_search`) | random_score (fallback in `get_semantic_sample`) |

No breaking changes. Every new code path has a BM25/random fallback.

---

## Implementation Order

| Step | File | What changes |
|---|---|---|
| 1 | `requirements.txt` | add `fastembed>=0.3.0` |
| 2 | `src/config.py` | add `EMBED_*` config vars |
| 3 | `src/datasource/embedding_client.py` | **new file** — `EmbeddingClient` singleton |
| 4 | `src/datasource/es_client.py` | `create_index()` mapping, `_check_vector_field()`, `_hybrid_search()` RRF, `get_semantic_sample()`, `invalidate_vector_cache()` |
| 5 | `src/worker/task_handlers.py` | `dispatch_task()` routing, `handle_embed_docs()`, wire into `handle_create_investigation()`, update `handle_insight_ai()` |
| 6 | `src/worker/kafka_producer.py` | add `embed_docs` to LLM-topic routing |
| 7 | `src/worker/kafka_consumer.py` | add `embed_docs` to `_LLM_TYPES` |
| 8 | `src/rag/retriever.py` | add `get_semantic_sample()` |
| 9 | `.env` / `.env.example` | add embedding env vars |

---

## Known Gotchas

**`fastembed` first-run download:** `bge-m3` (~570 MB ONNX) downloads from HuggingFace on first `embed()` call. Set `EMBED_CACHE_DIR` to a Docker volume to avoid re-downloading on each container restart.

**ES RRF requires ES 8.9+:** `rank.rrf` is GA in 8.13 (current). The catch block in `_hybrid_search()` falls back to BM25 if the query is rejected.

**`_has_vector_cache` is process-local:** In a multi-process deployment each Flask/Gunicorn worker has its own `ESClient`. After `invalidate_vector_cache()` runs in the Kafka worker process, API workers will auto-detect on next cache miss (next `search()` call). Worst case: one BM25-only response per API worker process after embedding completes. Tolerable.

**Large investigations:** `embed_docs` scrolls with a 5-minute scroll context. For >10k docs at batch_size=64 the task runs ~8 minutes. Either increase scroll TTL or migrate to `search_after` + PIT for very large corpora.

**`embed_docs` CPU vs LLM GPU contention:** Routing `embed_docs` through the LLM Kafka topic means it queues behind LLM tasks. With `LLM_PARALLEL=10` it can run in parallel with up to 9 concurrent LLM tasks. CPU embedding + GPU inference do not share resources, so parallel execution is safe — but watch CPU utilization. Set `EMBED_THREADS=4` (default) to cap embedding CPU use to ~4 cores.
