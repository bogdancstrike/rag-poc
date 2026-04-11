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
        self._default_index = Config.ES_INDEX
        self._has_vector_cache = {}  # lazily detected per index

    # ── Connectivity & Indices ──────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Return True if the ES cluster is reachable."""
        try:
            return self._client.ping()
        except Exception as e:
            logger.warning(f"[es] Connection test failed: {e}")
            return False

    def list_indices(self, pattern: str = "qsint_docs*") -> list[str]:
        """Return a list of available indices matching a pattern."""
        try:
            indices = self._client.indices.get_alias(index=pattern)
            return sorted(list(indices.keys()))
        except NotFoundError:
            return []
        except Exception as e:
            logger.error(f"[es] list_indices error: {e}")
            return []

    def get_index_stats(self, index_name: str = None) -> dict:
        """Return doc count, field names, and cluster health for the index."""
        idx = index_name or self._default_index
        try:
            info    = self._client.indices.stats(index=idx)
            mapping = self._client.indices.get_mapping(index=idx)
            health  = self._client.cluster.health()
            doc_count = info["indices"][idx]["primaries"]["docs"]["count"]
            fields = list(
                mapping.get(idx, {})
                .get("mappings", {})
                .get("properties", {})
                .keys()
            )
            return {
                "index":       idx,
                "doc_count":   doc_count,
                "fields":      fields,
                "status":      health.get("status", "unknown"),
                "has_vector":  self._check_vector_field(idx),
            }
        except NotFoundError:
            return {"index": idx, "doc_count": 0, "fields": [], "status": "missing"}
        except Exception as e:
            logger.error(f"[es] get_index_stats error: {e}")
            return {"error": str(e)}

    # ── Search ──────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 8, index_name: str = None) -> list[dict]:
        """Search the index and return normalised chunk dicts."""
        idx = index_name or self._default_index
        if self._check_vector_field(idx):
            return self._hybrid_search(query, top_k, idx)
        return self._keyword_search(query, top_k, idx)

    # ES query_string / multi_match clause limit. Queries longer than this
    # cause "Term too complex" errors with fuzziness enabled.
    _MAX_QUERY_LEN = 512

    def _keyword_search(self, query: str, top_k: int, index_name: str) -> list[dict]:
        """Standard multi-field BM25 search across text-like fields."""
        # Truncate long queries (e.g. user pasted a full document into chat).
        # Fuzziness is intentionally omitted: it amplifies clause-count on long
        # inputs and is not useful for intelligence document retrieval.
        q = query[:self._MAX_QUERY_LEN]
        try:
            resp = self._client.search(
                index=index_name,
                body={
                    "size": top_k,
                    "query": {
                        "multi_match": {
                            "query":  q,
                            "fields": ["text^3", "title^2", "content^2", "*"],
                            "type":   "best_fields",
                        }
                    },
                    "_source": True,
                },
            )
            return self._normalise_hits(resp["hits"]["hits"])
        except Exception as e:
            logger.error(f"[es] keyword search error: {e}")
            return []

    def _hybrid_search(self, query: str, top_k: int, index_name: str) -> list[dict]:
        """BM25 search only (KNN requires embeddings generation pipeline)."""
        return self._keyword_search(query, top_k, index_name)

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

    def get_sample_docs(self, n: int = 200, index_name: str = None) -> list[dict]:
        """Return up to n sampled documents for insights generation."""
        idx = index_name or self._default_index
        try:
            resp = self._client.search(
                index=idx,
                body={
                    "size": min(n, 1000),
                    "query": {
                        "function_score": {
                            "functions": [{
                                "random_score": {
                                    "seed": 42,
                                    "field": "_seq_no"
                                }
                            }],
                            "boost_mode": "replace"
                        }
                    },
                    "_source": True,
                },
            )
            return self._normalise_hits(resp["hits"]["hits"])
        except Exception as e:
            logger.error(f"[es] sample error: {e}")
            return []

    # ── Raw Documents & Aggregations ────────────────────────────────────────────

    def get_aggregations(self, index_name: str = None) -> dict:
        """Perform static analysis using Elasticsearch aggregations."""
        idx = index_name or self._default_index
        try:
            body = {
                "size": 0,
                "aggs": {
                    "platforms": {"terms": {"field": "platform.keyword", "size": 10}},
                    "regions": {"terms": {"field": "region.keyword", "size": 10}},
                    "topics": {"terms": {"field": "topic.keyword", "size": 50}},
                    "sentiments": {"terms": {"field": "sentiment.keyword", "size": 10}},
                    "entities": {"terms": {"field": "entity.keyword", "size": 10}},
                }
            }
            resp = self._client.search(index=idx, body=body)
            aggs = resp.get("aggregations", {})
            return {
                "platforms": [{"label": b["key"], "value": b["doc_count"]} for b in aggs.get("platforms", {}).get("buckets", [])],
                "regions": [{"label": b["key"], "value": b["doc_count"]} for b in aggs.get("regions", {}).get("buckets", [])],
                "topics": [{"label": b["key"], "value": b["doc_count"]} for b in aggs.get("topics", {}).get("buckets", [])],
                "sentiments": [{"label": b["key"], "value": b["doc_count"]} for b in aggs.get("sentiments", {}).get("buckets", [])],
                "entities": [{"label": b["key"], "value": b["doc_count"]} for b in aggs.get("entities", {}).get("buckets", [])],
            }
        except Exception as e:
            logger.error(f"[es] get_aggregations error: {e}")
            return {}

    def get_documents(
        self,
        index_name: str = None,
        offset: int = 0,
        limit: int = 50,
        query: str = None,
        id_filter: Optional[list] = None,
        sentiment_filter: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """Get raw documents for tabular exploration. Returns (docs, total_count).

        Args:
            id_filter:        If provided, restrict results to these document IDs.
                              Pass an empty list [] to indicate no docs match (returns 0 results).
            sentiment_filter: If provided, add a term filter on the sentiment.keyword field.
        """
        idx = index_name or self._default_index

        # Caller signals "no matching docs" by passing an empty id list
        if id_filter is not None and len(id_filter) == 0:
            return [], 0

        try:
            filters = []
            if id_filter:
                filters.append({"ids": {"values": id_filter}})
            if sentiment_filter:
                filters.append({"term": {"sentiment.keyword": sentiment_filter}})

            if query:
                text_query = {
                    "query_string": {"query": query, "default_operator": "AND"}
                }
            else:
                text_query = {"match_all": {}}

            if filters:
                body_query = {
                    "bool": {
                        "must": text_query,
                        "filter": filters,
                    }
                }
            else:
                body_query = text_query

            body = {
                "from": offset,
                "size": limit,
                "_source": True,
                "sort": [{"created_at": {"order": "desc", "unmapped_type": "date"}}],
                "query": body_query,
            }

            resp = self._client.search(index=idx, body=body)
            hits = resp["hits"]["hits"]
            total = resp["hits"]["total"]["value"]
            docs = [{"id": hit["_id"], **hit["_source"]} for hit in hits]
            return docs, total
        except Exception as e:
            logger.error(f"[es] get_documents error: {e}")
            return [], 0

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _check_vector_field(self, index_name: str) -> bool:
        """Detect whether the index has a dense_vector field (cached)."""
        if index_name in self._has_vector_cache:
            return self._has_vector_cache[index_name]
        try:
            mapping = self._client.indices.get_mapping(index=index_name)
            props   = (
                mapping.get(index_name, {})
                .get("mappings", {})
                .get("properties", {})
            )
            has_vector = any(
                v.get("type") == "dense_vector" for v in props.values()
            )
            self._has_vector_cache[index_name] = has_vector
            return has_vector
        except Exception:
            self._has_vector_cache[index_name] = False
            return False

    def get_document_text(self, doc_id: str, index_name: str = None) -> str:
        """Fetch a single document by ID and return its text content.

        Uses the direct GET API (not search) for reliability.
        Tries the same field fallback chain as _normalise_hits.
        Returns an empty string if the document is not found or has no text.
        """
        idx = index_name or self._default_index
        try:
            resp = self._client.get(index=idx, id=doc_id)
            src = resp.get("_source") or {}
            return (
                src.get("text") or src.get("content") or src.get("body")
                or src.get("description") or ""
            ).strip()
        except NotFoundError:
            logger.warning(f"[es] get_document_text: doc not found id={doc_id} index={idx}")
            return ""
        except Exception as e:
            logger.error(f"[es] get_document_text error id={doc_id}: {e}")
            return ""

    def index_document(self, doc_id: str, body: dict, index_name: str = None) -> bool:
        """Index (upsert) a single document. Used by seed scripts and tests."""
        idx = index_name or self._default_index
        try:
            self._client.index(index=idx, id=doc_id, document=body)
            return True
        except Exception as e:
            logger.error(f"[es] index_document error: {e}")
            return False

    def ensure_index(self, index_name: str = None) -> None:
        """Create the index with basic mappings if it does not exist."""
        idx = index_name or self._default_index
        if self._client.indices.exists(index=idx):
            return
        self._client.indices.create(
            index=idx,
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
        logger.info(f"[es] Created index '{idx}'")

    # ── Investigation / multi-index helpers ────────────────────────────────────

    def search_all_indices(
        self,
        query: str = "",
        offset: int = 0,
        limit: int = 50,
        sentiment_filter: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        index_pattern: str = "qsint_docs*",
    ) -> tuple[list[dict], int]:
        """Multi-index document search for global Data Exploration.

        Returns (docs, total_count).  Each doc includes ``_source_index`` so
        the frontend knows which ES index the document came from (needed for
        per-doc actions like enrich/status/labels that are keyed by datasource).
        """
        try:
            filters = []
            if sentiment_filter:
                filters.append({"term": {"sentiment.keyword": sentiment_filter}})
            if date_from or date_to:
                range_clause: dict = {}
                if date_from:
                    range_clause["gte"] = date_from
                if date_to:
                    range_clause["lte"] = date_to
                filters.append({"range": {"created_at": range_clause}})

            if query:
                q = query[:self._MAX_QUERY_LEN]
                text_query = {"query_string": {"query": q, "default_operator": "AND"}}
            else:
                text_query = {"match_all": {}}

            body_query = (
                {"bool": {"must": text_query, "filter": filters}}
                if filters
                else text_query
            )

            body = {
                "from": offset,
                "size": limit,
                "_source": True,
                "sort": [{"created_at": {"order": "desc", "unmapped_type": "date"}}],
                "query": body_query,
            }

            resp = self._client.search(index=index_pattern, body=body)
            hits = resp["hits"]["hits"]
            total = resp["hits"]["total"]["value"]
            docs = [
                {"id": h["_id"], "_source_index": h["_index"], **h["_source"]}
                for h in hits
            ]
            return docs, total
        except Exception as e:
            logger.error(f"[es] search_all_indices error: {e}")
            return [], 0

    def create_index(self, index_name: str, mapping: Optional[dict] = None) -> bool:
        """Create a new index.  Returns True on success, False if already exists."""
        try:
            if self._client.indices.exists(index=index_name):
                logger.info(f"[es] create_index: '{index_name}' already exists")
                return False
            body = mapping or {
                "mappings": {
                    "properties": {
                        "text":           {"type": "text"},
                        "title":          {"type": "text"},
                        "content":        {"type": "text"},
                        "source":         {"type": "keyword"},
                        "platform":       {"type": "keyword"},
                        "region":         {"type": "keyword"},
                        "topic":          {"type": "keyword"},
                        "sentiment":      {"type": "keyword"},
                        "classification": {"type": "keyword"},
                        "created_at":     {"type": "date"},
                        "tags":           {"type": "keyword"},
                    }
                }
            }
            self._client.indices.create(index=index_name, body=body)
            logger.info(f"[es] Created investigation index '{index_name}'")
            return True
        except Exception as e:
            logger.error(f"[es] create_index error for '{index_name}': {e}")
            raise

    def copy_documents(
        self,
        source_indices: list[str],
        query_body: dict,
        dest_index: str,
        batch_size: int = 500,
    ) -> int:
        """Scroll through source_indices matching query_body and bulk-index into dest_index.

        Returns the total number of documents copied.
        """
        from elasticsearch import helpers as es_helpers

        total_copied = 0
        scroll_id = None
        try:
            resp = self._client.search(
                index=",".join(source_indices) if source_indices else "qsint_docs*",
                body={**query_body, "size": batch_size},
                scroll="2m",
            )
            scroll_id = resp.get("_scroll_id")

            while True:
                hits = resp["hits"]["hits"]
                if not hits:
                    break

                actions = [
                    {
                        "_index": dest_index,
                        "_id":    h["_id"],
                        "_source": h["_source"],
                    }
                    for h in hits
                ]
                success, _ = es_helpers.bulk(self._client, actions, raise_on_error=False)
                total_copied += success

                if not scroll_id:
                    break
                resp = self._client.scroll(scroll_id=scroll_id, scroll="2m")
                scroll_id = resp.get("_scroll_id")

        finally:
            if scroll_id:
                try:
                    self._client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    pass

        # Refresh so newly indexed docs are immediately searchable
        try:
            self._client.indices.refresh(index=dest_index)
        except Exception as e:
            logger.warning(f"[es] refresh failed for '{dest_index}': {e}")

        logger.info(f"[es] Copied {total_copied} docs → '{dest_index}'")
        return total_copied

    def delete_index(self, index_name: str) -> bool:
        """Delete an index.  Returns True if deleted, False if not found."""
        try:
            if not self._client.indices.exists(index=index_name):
                return False
            self._client.indices.delete(index=index_name)
            logger.info(f"[es] Deleted index '{index_name}'")
            return True
        except Exception as e:
            logger.error(f"[es] delete_index error for '{index_name}': {e}")
            return False
