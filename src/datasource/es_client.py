"""Elasticsearch 8 datasource client.

Provides keyword (BM25) search and random sampling for the RAG pipeline.
If the index contains a 'vector' field the client upgrades automatically
to a hybrid BM25 + KNN search (requires ES 8.x dense_vector support).
"""
import random
from typing import Optional

from elasticsearch import Elasticsearch, NotFoundError
from framework.commons.logger import logger

from src.config import Config


class ESClient:
    """Thin wrapper around the official elasticsearch-py 8.x client."""

    def __init__(self):
        kwargs = {"hosts": [Config.ES_HOST]}
        if Config.ES_USER and Config.ES_PASSWORD:
            kwargs["basic_auth"] = (Config.ES_USER, Config.ES_PASSWORD)
        self._client = Elasticsearch(**kwargs)
        self._index  = Config.ES_INDEX
        self._has_vector: Optional[bool] = None   # lazily detected

    # ── Connectivity ────────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Return True if the ES cluster is reachable."""
        try:
            return self._client.ping()
        except Exception as e:
            logger.warning(f"[es] Connection test failed: {e}")
            return False

    def get_index_stats(self) -> dict:
        """Return doc count, field names, and cluster health for the index."""
        try:
            info    = self._client.indices.stats(index=self._index)
            mapping = self._client.indices.get_mapping(index=self._index)
            health  = self._client.cluster.health()
            doc_count = info["_all"]["primaries"]["docs"]["count"]
            fields = list(
                mapping.get(self._index, {})
                .get("mappings", {})
                .get("properties", {})
                .keys()
            )
            return {
                "index":       self._index,
                "doc_count":   doc_count,
                "fields":      fields,
                "status":      health.get("status", "unknown"),
                "has_vector":  self._check_vector_field(),
            }
        except NotFoundError:
            return {"index": self._index, "doc_count": 0, "fields": [], "status": "missing"}
        except Exception as e:
            logger.error(f"[es] get_index_stats error: {e}")
            return {"error": str(e)}

    # ── Search ──────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 8) -> list[dict]:
        """Search the index and return normalised chunk dicts.

        Uses hybrid BM25+KNN when a vector field is present, pure BM25 otherwise.
        Each result: {id, text, score, source, metadata}
        """
        if self._check_vector_field():
            return self._hybrid_search(query, top_k)
        return self._keyword_search(query, top_k)

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """Standard multi-field BM25 search across text-like fields."""
        try:
            resp = self._client.search(
                index=self._index,
                body={
                    "size": top_k,
                    "query": {
                        "multi_match": {
                            "query":  query,
                            "fields": ["text^3", "title^2", "content^2", "*"],
                            "type":   "best_fields",
                            "fuzziness": "AUTO",
                        }
                    },
                    "_source": True,
                },
            )
            return self._normalise_hits(resp["hits"]["hits"])
        except Exception as e:
            logger.error(f"[es] keyword search error: {e}")
            return []

    def _hybrid_search(self, query: str, top_k: int) -> list[dict]:
        """BM25 search only (KNN requires embeddings generation pipeline).

        Placeholder — when an embedding endpoint is configured, replace
        the body with a combined knn + query clause for true hybrid search.
        """
        return self._keyword_search(query, top_k)

    def _normalise_hits(self, hits: list) -> list[dict]:
        """Convert raw ES hits to the common {id, text, score, source, metadata} shape."""
        results = []
        for hit in hits:
            src  = hit.get("_source", {})
            text = (
                src.get("text")
                or src.get("content")
                or src.get("body")
                or src.get("description")
                or str(src)[:500]
            )
            results.append({
                "id":       hit["_id"],
                "text":     text,
                "score":    round(hit.get("_score", 0.0), 4),
                "source":   "elasticsearch",
                "metadata": {k: v for k, v in src.items() if k not in ("text", "content", "body")},
            })
        return results

    # ── Sampling ────────────────────────────────────────────────────────────────

    def get_sample_docs(self, n: int = 200) -> list[dict]:
        """Return up to n randomly sampled documents for insights generation."""
        try:
            resp = self._client.search(
                index=self._index,
                body={
                    "size": min(n, 1000),
                    "query": {"function_score": {"functions": [{"random_score": {}}]}},
                    "_source": True,
                },
            )
            return self._normalise_hits(resp["hits"]["hits"])
        except Exception as e:
            logger.error(f"[es] sample error: {e}")
            return []

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _check_vector_field(self) -> bool:
        """Detect whether the index has a dense_vector field (cached)."""
        if self._has_vector is not None:
            return self._has_vector
        try:
            mapping = self._client.indices.get_mapping(index=self._index)
            props   = (
                mapping.get(self._index, {})
                .get("mappings", {})
                .get("properties", {})
            )
            self._has_vector = any(
                v.get("type") == "dense_vector" for v in props.values()
            )
        except Exception:
            self._has_vector = False
        return self._has_vector

    def index_document(self, doc_id: str, body: dict) -> bool:
        """Index (upsert) a single document. Used by seed scripts and tests."""
        try:
            self._client.index(index=self._index, id=doc_id, document=body)
            return True
        except Exception as e:
            logger.error(f"[es] index_document error: {e}")
            return False

    def ensure_index(self) -> None:
        """Create the index with basic mappings if it does not exist."""
        if self._client.indices.exists(index=self._index):
            return
        self._client.indices.create(
            index=self._index,
            body={
                "mappings": {
                    "properties": {
                        "text":       {"type": "text"},
                        "title":      {"type": "text"},
                        "source":     {"type": "keyword"},
                        "created_at": {"type": "date"},
                        "tags":       {"type": "keyword"},
                    }
                }
            },
        )
        logger.info(f"[es] Created index '{self._index}'")
