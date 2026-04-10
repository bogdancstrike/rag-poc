"""Unified retrieval interface.

Delegates to Elasticsearch or the file loader depending on DATASOURCE_TYPE config.
Both backends return the same normalised shape: {id, text, score, source, metadata}.
"""
from framework.commons.logger import logger
from framework.tracing import get_tracer

from src.config import Config

tracer = get_tracer()


class Retriever:
    """Single retrieval entry-point used by the chat and insights pipelines."""

    def __init__(self):
        self._es_client   = None
        self._file_loader = None
        self._init()

    def _init(self) -> None:
        """Lazily initialise the active datasource backend."""
        if Config.DATASOURCE_TYPE == "file":
            from src.datasource.file_loader import FileLoader
            self._file_loader = FileLoader(Config.FILE_DATASOURCE_PATH)
            self._file_loader.load()
            logger.info(f"[retriever] Using file datasource: {Config.FILE_DATASOURCE_PATH}")
        else:
            from src.datasource.es_client import ESClient
            self._es_client = ESClient()
            logger.info(f"[retriever] Using Elasticsearch datasource: {Config.ES_HOST}/{Config.ES_INDEX}")

    # ── Public API ──────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = None, index_name: str = None) -> list[dict]:
        """Retrieve the most relevant document chunks for a query."""
        k = top_k or Config.RAG_TOP_K
        with tracer.start_as_current_span("rag.retrieve") as span:
            span.set_attribute("retrieve.query_length", len(query))
            span.set_attribute("retrieve.top_k", k)
            span.set_attribute("retrieve.backend", "file" if self._file_loader else "elasticsearch")
            if index_name:
                span.set_attribute("retrieve.index_name", index_name)
            try:
                if self._file_loader:
                    results = self._file_loader.search(query, k)
                elif self._es_client:
                    results = self._es_client.search(query, k, index_name=index_name)
                else:
                    results = []
                span.set_attribute("retrieve.results_count", len(results))
                return results
            except Exception as e:
                logger.error(f"[retriever] retrieve error: {e}", exc_info=True)
                span.set_attribute("retrieve.error", str(e))
                return []

    def get_sample(self, n: int = None, index_name: str = None) -> list[dict]:
        """Return a random sample of documents for insights generation."""
        count = n or Config.INSIGHTS_MAX_DOCS
        with tracer.start_as_current_span("rag.sample") as span:
            span.set_attribute("sample.count_requested", count)
            span.set_attribute("sample.backend", "file" if self._file_loader else "elasticsearch")
            if index_name:
                span.set_attribute("sample.index_name", index_name)
            try:
                if self._file_loader:
                    results = self._file_loader.get_sample(count)
                elif self._es_client:
                    results = self._es_client.get_sample_docs(count, index_name=index_name)
                else:
                    results = []
                span.set_attribute("sample.count_returned", len(results))
                return results
            except Exception as e:
                logger.error(f"[retriever] get_sample error: {e}", exc_info=True)
                span.set_attribute("sample.error", str(e))
                return []

    def get_status(self, index_name: str = None) -> dict:
        """Return connectivity / stats info about the active datasource."""
        try:
            if self._file_loader:
                return {"type": "file", **self._file_loader.get_stats()}
            if self._es_client:
                return {"type": "elasticsearch", **self._es_client.get_index_stats(index_name=index_name)}
        except Exception as e:
            return {"type": Config.DATASOURCE_TYPE, "error": str(e)}
        return {"type": "none"}


# Module-level singleton — created once and reused across requests
_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    """Return the module-level Retriever singleton."""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
