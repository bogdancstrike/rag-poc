"""Insights generation engine.

Samples the corpus, calls the LLM to extract structured intelligence
(hot topics, narratives, trends, entities, anomalies), and caches the
result in Postgres with a configurable TTL.
"""
import json
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

from framework.commons.logger import logger
from framework.tracing import get_tracer

from src.config import Config

tracer = get_tracer()
from src.rag.retriever import get_retriever
from src.rag.llm_client import get_llm
from src.rag.prompt_builder import PromptBuilder

# Thread lock prevents multiple concurrent regeneration calls
_lock = threading.Lock()


class InsightsEngine:
    """Generates and caches AI-powered intelligence reports from the corpus."""

    def __init__(self):
        self._prompt_builder = PromptBuilder()

    # ── Public API ──────────────────────────────────────────────────────────────

    def get_insights(self, datasource: str = "default", force_refresh: bool = False) -> dict:
        """Return cached insights or generate fresh ones if stale.

        Thread-safe: only one generation runs at a time per process.
        The TTL is checked against InsightsCache.generated_at.
        """
        with tracer.start_as_current_span("insights.get") as span:
            span.set_attribute("insights.datasource", datasource)
            span.set_attribute("insights.force_refresh", force_refresh)

            if not force_refresh:
                cached = self._load_from_cache(datasource)
                if cached:
                    logger.debug(f"[insights] Cache hit for datasource={datasource}")
                    span.set_attribute("insights.cache_hit", True)
                    return cached

            span.set_attribute("insights.cache_hit", False)
            logger.info(f"[insights] Generating fresh insights for datasource={datasource}")
            with _lock:
                # Double-check after acquiring lock (another thread may have just generated)
                if not force_refresh:
                    cached = self._load_from_cache(datasource)
                    if cached:
                        return cached
                return self._generate_and_cache(datasource)

    def invalidate(self, datasource: str = "default") -> None:
        """Delete cached insights, forcing regeneration on next call."""
        from src.session.models import InsightsCache, get_db
        with get_db() as db:
            db.query(InsightsCache).filter(InsightsCache.datasource == datasource).delete()
        logger.info(f"[insights] Cache invalidated for datasource={datasource}")

    # ── Internal ────────────────────────────────────────────────────────────────

    def _load_from_cache(self, datasource: str) -> Optional[dict]:
        """Load cached insights if they are still within TTL."""
        try:
            from src.session.models import InsightsCache, get_db
            with get_db() as db:
                row = (
                    db.query(InsightsCache)
                    .filter(InsightsCache.datasource == datasource)
                    .order_by(InsightsCache.generated_at.desc())
                    .first()
                )
                if row is None:
                    return None

                age_sec = (
                    datetime.now(timezone.utc) - row.generated_at.replace(tzinfo=timezone.utc)
                ).total_seconds()

                if age_sec > Config.INSIGHTS_CACHE_TTL:
                    logger.debug(f"[insights] Cache expired (age={age_sec:.0f}s)")
                    return None

                return {
                    **row.payload,
                    "_meta": {
                        "cached":       True,
                        "generated_at": row.generated_at.isoformat(),
                        "age_seconds":  int(age_sec),
                        "datasource":   datasource,
                    },
                }
        except Exception as e:
            logger.warning(f"[insights] Cache read error: {e}")
            return None

    def _generate_and_cache(self, datasource: str) -> dict:
        """Sample corpus, call LLM, parse JSON, persist to cache, return result."""
        with tracer.start_as_current_span("insights.generate") as span:
            span.set_attribute("insights.datasource", datasource)

            retriever = get_retriever()
            llm       = get_llm()

            # 1. Sample documents
            sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS)
            span.set_attribute("insights.sample_count", len(sample))
            if not sample:
                logger.warning("[insights] No documents to analyse — returning empty insights")
                span.set_attribute("insights.empty_reason", "no_documents")
                return self._empty_insights(datasource, reason="No documents in corpus")

            # 2. Build prompt and call LLM
            messages, system = self._prompt_builder.build_insights_messages(sample)
            try:
                raw = llm.complete_json(messages, system)
            except Exception as e:
                logger.error(f"[insights] LLM call failed: {e}", exc_info=True)
                span.set_attribute("insights.error", str(e))
                return self._empty_insights(datasource, reason=f"LLM error: {e}")

            # 3. Parse LLM JSON response (strip markdown fences if present)
            payload = self._parse_json(raw)
            if not payload:
                logger.error(f"[insights] Could not parse LLM response (first 500 chars): {raw[:500]}")
                span.set_attribute("insights.error", "json_parse_error")
                return self._empty_insights(datasource, reason="JSON parse error")

            span.set_attribute("insights.hot_topics_count", len(payload.get("hot_topics", [])))
            span.set_attribute("insights.narratives_count", len(payload.get("narratives", [])))
            span.set_attribute("insights.trends_count", len(payload.get("trends", [])))

            # 4. Persist to Postgres
            self._save_to_cache(datasource, payload)

            return {
                **payload,
                "_meta": {
                    "cached":       False,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "doc_count":    len(sample),
                    "datasource":   datasource,
                },
            }

    def _save_to_cache(self, datasource: str, payload: dict) -> None:
        """Upsert the insights payload into the Postgres cache table."""
        try:
            from src.session.models import InsightsCache, get_db
            with get_db() as db:
                row = (
                    db.query(InsightsCache)
                    .filter(InsightsCache.datasource == datasource)
                    .first()
                )
                if row:
                    row.payload      = payload
                    row.generated_at = datetime.now(timezone.utc)
                else:
                    db.add(InsightsCache(datasource=datasource, payload=payload))
        except Exception as e:
            logger.error(f"[insights] Cache write error: {e}", exc_info=True)

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """Strip markdown fences and parse JSON. Returns None on failure."""
        # Remove ```json ... ``` fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        # Remove trailing ``` if any
        cleaned = cleaned.rstrip("`").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to extract the first JSON object via brute-force
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return None

    @staticmethod
    def _empty_insights(datasource: str, reason: str = "") -> dict:
        return {
            "hot_topics": [],
            "narratives": [],
            "trends":     [],
            "entities":   [],
            "anomalies":  [],
            "_meta": {
                "cached":     False,
                "datasource": datasource,
                "reason":     reason,
            },
        }


# Module-level singleton
_engine: InsightsEngine | None = None


def get_insights_engine() -> InsightsEngine:
    global _engine
    if _engine is None:
        _engine = InsightsEngine()
    return _engine
