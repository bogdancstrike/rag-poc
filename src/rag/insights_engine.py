"""Insights generation engine with background tasking.

Samples the corpus and triggers multiple background tasks:
1. AI Summary (hot topics, narratives, trends)
2. AI NER (Named Entity Recognition)
3. AI Graph (Relationship detection)
4. Data Statistics (Chart data from Elasticsearch)

Uses ThreadPoolExecutor for lightweight background processing.
"""
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional, List, Dict

from framework.commons.logger import logger
from framework.tracing import get_tracer

from src.config import Config
from src.rag.retriever import get_retriever
from src.rag.llm_client import get_llm
from src.rag.prompt_builder import PromptBuilder

tracer = get_tracer()

# Background worker pool
_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.Lock()


class InsightsEngine:
    """Orchestrates background intelligence tasks."""

    def __init__(self):
        self._prompt_builder = PromptBuilder()

    # ── Public API ──────────────────────────────────────────────────────────────

    def get_insights(self, datasource: str = "default", force_refresh: bool = False) -> dict:
        """Return currently available insights and trigger background updates if needed.
        
        This call is non-blocking. If tasks are pending, it returns current state.
        """
        with tracer.start_as_current_span("insights.get_all") as span:
            span.set_attribute("insights.datasource", datasource)
            
            # 1. Load current state from DB first
            current_insights = self._load_all_from_cache(datasource)
            
            # 2. Check if we have active tasks in flight (less than 10 mins old)
            now = datetime.now(timezone.utc)
            is_processing = False
            for t in current_insights.values():
                if t.get("status") in ("pending", "processing"):
                    gen_at = self._parse_iso_utc(t.get("generated_at"))
                    if gen_at and (now - gen_at).total_seconds() < 600: # 10 mins timeout for "stuck" tasks
                        is_processing = True
                        break
            
            # 3. Decision logic: do we need to start a fresh generation?
            needs_refresh = force_refresh
            
            if not needs_refresh and not is_processing:
                if not current_insights:
                    needs_refresh = True
                else:
                    # Check TTL on summary (primary anchor)
                    summary = current_insights.get("summary")
                    if summary:
                        gen_at = self._parse_iso_utc(summary.get("generated_at"))
                        if gen_at:
                            age = (now - gen_at).total_seconds()
                            if age > Config.INSIGHTS_CACHE_TTL:
                                logger.info(f"[insights] TTL expired ({age:.0f}s)")
                                needs_refresh = True
                        else:
                            needs_refresh = True

            if needs_refresh:
                logger.info(f"[insights] Triggering fresh refresh for {datasource} (forced={force_refresh})")
                retriever = get_retriever()
                sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS, index_name=datasource)
                if not sample:
                    return self._empty_response(datasource, "No documents")

                doc_ids = sorted([str(d.get("id")) for d in sample])
                sample_hash = hashlib.sha256(",".join(doc_ids).encode()).hexdigest()
                
                self._trigger_tasks(datasource, sample, sample_hash)
                # Re-load to get the "pending" statuses
                current_insights = self._load_all_from_cache(datasource)
                span.set_attribute("insights.refresh_triggered", True)
            else:
                span.set_attribute("insights.refresh_triggered", False)

            return {
                "tasks": current_insights,
                "_meta": {
                    "datasource": datasource,
                    "is_processing": is_processing,
                    "refresh_triggered": needs_refresh
                }
            }

    def invalidate(self, datasource: str = "default") -> None:
        """Delete cached insights, forcing regeneration on next call."""
        from src.session.models import InsightsCache, get_db
        with get_db() as db:
            db.query(InsightsCache).filter(InsightsCache.datasource == datasource).delete()
        logger.info(f"[insights] Cache invalidated for datasource={datasource}")

    # ── Task Orchestration ──────────────────────────────────────────────────────

    def _trigger_tasks(self, datasource: str, sample: List[dict], sample_hash: str):
        """Initialize 'pending' rows and submit to executor."""
        tasks = ["summary", "ner", "graph", "stats"]
        for ttype in tasks:
            self._set_task_status(datasource, ttype, "pending", sample_hash, clear_data=True)
            if ttype == "stats":
                _executor.submit(self._run_stats_task, datasource, sample_hash)
            else:
                _executor.submit(self._run_ai_task, datasource, ttype, sample, sample_hash)

    def _run_ai_task(self, datasource: str, ttype: str, sample: List[dict], sample_hash: str):
        """Worker function for LLM tasks."""
        with tracer.start_as_current_span(f"insights.task.{ttype}") as span:
            self._set_task_status(datasource, ttype, "processing", sample_hash)
            logger.info(f"[insights] Starting AI task: {ttype}")
            
            try:
                llm = get_llm()
                messages, system = self._prompt_builder.build_insights_messages(sample, task_type=ttype)
                raw = llm.complete_json(messages, system)
                logger.debug(f"[insights] LLM response: {raw[:500]}...")
                
                payload = self._parse_json(raw)
                if not payload:
                    logger.error(f"[insights] {ttype} JSON parse fail. Raw output: {raw[:500]}...")
                    raise ValueError(f"Failed to parse {ttype} JSON from LLM")
                
                self._set_task_status(datasource, ttype, "complete", sample_hash, payload=payload)
                logger.info(f"[insights] Task {ttype} complete")
            except Exception as e:
                logger.error(f"[insights] Task {ttype} failed: {e}")
                self._set_task_status(datasource, ttype, "error", sample_hash, error=str(e))

    def _run_stats_task(self, datasource: str, sample_hash: str):
        """Compute statistics from the datasource directly."""
        with tracer.start_as_current_span("insights.task.stats") as span:
            self._set_task_status(datasource, "stats", "processing", sample_hash)
            try:
                retriever = get_retriever()
                status = retriever.get_status(datasource)
                doc_count = status.get("doc_count", 0)
                
                aggs = retriever.get_aggregations(datasource)
                
                payload = {
                    "doc_count": doc_count,
                    "platforms": aggs.get("platforms", []),
                    "regions": aggs.get("regions", []),
                    "topics": aggs.get("topics", []),
                    "sentiments": aggs.get("sentiments", []),
                    "entities": aggs.get("entities", []),
                    # Keep distribution/timeline dummy for now or replace with actual
                    "distribution": aggs.get("platforms", [])[:3],
                    "timeline": [
                        {"date": "2026-04-01", "count": int(doc_count * 0.1)},
                        {"date": "2026-04-05", "count": int(doc_count * 0.4)},
                        {"date": "2026-04-10", "count": int(doc_count * 0.3)}
                    ]
                }
                self._set_task_status(datasource, "stats", "complete", sample_hash, payload=payload)
            except Exception as e:
                logger.error(f"[insights] Stats task failed: {e}", exc_info=True)
                self._set_task_status(datasource, "stats", "error", sample_hash, error=str(e))

    # ── DB Helpers ──────────────────────────────────────────────────────────────

    def _load_all_from_cache(self, datasource: str) -> Dict[str, dict]:
        from src.session.models import InsightsCache, get_db
        try:
            with get_db() as db:
                rows = db.query(InsightsCache).filter(InsightsCache.datasource == datasource).all()
                return {r.insight_type: r.to_dict() for r in rows}
        except Exception as e:
            logger.error(f"Failed to load insights: {e}")
            return {}

    def get_all_tasks(self) -> dict:
        """Return a platform-wide overview of all tasks (insights & enrichments)."""
        from src.session.models import InsightsCache, DocumentEnrichment, get_db
        try:
            with get_db() as db:
                insight_rows = db.query(InsightsCache).all()
                enrich_rows = db.query(DocumentEnrichment).all()
                
                insights = [r.to_dict() for r in insight_rows]
                enrichments = [r.to_dict() for r in enrich_rows]
                
                return {
                    "insights": insights,
                    "enrichments": enrichments,
                    "summary": {
                        "total_insights": len(insights),
                        "total_enrichments": len(enrichments),
                        "insights_pending": sum(1 for r in insights if r["status"] in ("pending", "processing")),
                        "enrichments_pending": sum(1 for r in enrichments if r["status"] in ("pending", "processing")),
                        "insights_error": sum(1 for r in insights if r["status"] == "error"),
                        "enrichments_error": sum(1 for r in enrichments if r["status"] == "error"),
                    }
                }
        except Exception as e:
            logger.error(f"Failed to load all tasks: {e}")
            return {"error": str(e)}

    def _set_task_status(self, datasource: str, ttype: str, status: str, sample_hash: str, payload=None, error=None, clear_data=False):
        from src.session.models import InsightsCache, get_db
        with _lock:
            try:
                with get_db() as db:
                    row = db.query(InsightsCache).filter(
                        InsightsCache.datasource == datasource,
                        InsightsCache.insight_type == ttype
                    ).first()
                    if not row:
                        row = InsightsCache(datasource=datasource, insight_type=ttype)
                        db.add(row)
                    row.status = status
                    row.sample_hash = sample_hash
                    row.generated_at = datetime.now(timezone.utc)
                    if clear_data:
                        row.payload = None
                        row.error = None
                    else:
                        if payload is not None: row.payload = payload
                        if error is not None: row.error = error
                    db.commit()
            except Exception as e:
                logger.error(f"Failed DB update for {ttype}: {e}")

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_iso_utc(ts_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO string and ensure it has UTC offset."""
        if not ts_str: return None
        try:
            # Handle Z suffix
            if ts_str.endswith("Z"):
                ts_str = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """Strip markdown fences and handle common malformed JSON issues."""
        if not raw: return None
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        cleaned = re.sub(r",\s*}", "}", cleaned)
        cleaned = re.sub(r"//.*", "", cleaned)

        def _extract_known_keys(data: dict) -> dict:
            # If the LLM wrapped the response in a rogue top-level key, unwrap it
            if isinstance(data, dict):
                # Check if it already has the expected keys
                if any(k in data for k in ("hot_topics", "entities", "nodes", "edges", "trends", "narratives")):
                    return data
                # Otherwise, search values for expected keys
                for v in data.values():
                    if isinstance(v, dict) and any(k in v for k in ("hot_topics", "entities", "nodes", "edges", "trends", "narratives")):
                        return v
            return data

        try:
            return _extract_known_keys(json.loads(cleaned))
        except json.JSONDecodeError:
            # Last resort: extract first { ... }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                try: 
                    return _extract_known_keys(json.loads(cleaned[start:end+1]))
                except: pass
        return None

    @staticmethod
    def _empty_response(datasource: str, reason: str) -> dict:
        return {"tasks": {}, "_meta": {"datasource": datasource, "reason": reason}}


_engine: InsightsEngine | None = None

def get_insights_engine() -> InsightsEngine:
    global _engine
    if _engine is None: _engine = InsightsEngine()
    return _engine
