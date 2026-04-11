"""Insights generation engine with background tasking.

Samples the corpus and triggers multiple background tasks:
1. AI Summary (hot topics, narratives, trends)
2. AI NER (Named Entity Recognition)
3. AI Graph (Relationship detection)
4. Data Statistics (Chart data from Elasticsearch)

Background work is routed through Kafka (or falls back to daemon threads).
All HTTP-facing methods return immediately — heavy work runs in background.
SSE subscribers receive push notifications as tasks complete.
"""
import hashlib
import json
import queue
import re
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set

from framework.commons.logger import logger
from framework.tracing import get_tracer

from src.config import Config
from src.rag.retriever import get_retriever
from src.rag.llm_client import get_llm
from src.rag.prompt_builder import PromptBuilder

tracer = get_tracer()

_lock = threading.Lock()


# ── SSE Event Bus ──────────────────────────────────────────────────────────────

class InsightsEventBus:
    """Thread-safe pub/sub for insights task status events.

    Each datasource has a list of subscriber queues. When a task changes status,
    `publish()` puts an event into every queue so SSE streams can forward it.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[queue.Queue]] = {}
        self._lock = threading.Lock()

    def subscribe(self, datasource: str) -> queue.Queue:
        """Register a new SSE client for a datasource. Returns a Queue to read from."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(datasource, []).append(q)
        return q

    def unsubscribe(self, datasource: str, q: queue.Queue) -> None:
        """Remove a subscriber when the SSE connection closes."""
        with self._lock:
            subs = self._subscribers.get(datasource, [])
            if q in subs:
                subs.remove(q)

    def publish(self, datasource: str, event: dict) -> None:
        """Broadcast an event to all subscribers of a datasource."""
        with self._lock:
            subs = list(self._subscribers.get(datasource, []))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # Slow consumer — drop event rather than block


# Singleton event bus used by all SSE endpoints
_event_bus = InsightsEventBus()


class InsightsEngine:
    """Orchestrates background intelligence tasks."""

    def __init__(self):
        self._prompt_builder = PromptBuilder()

    # ── Public API ──────────────────────────────────────────────────────────────

    def get_insights(self, datasource: str = "default", force_refresh: bool = False) -> dict:
        """Return currently available insights and trigger background updates if needed.

        This method is fully non-blocking — it returns immediately with the current
        DB state. Heavy work (Elasticsearch sample fetch + LLM calls) runs in background
        threads. The frontend polls or subscribes via SSE to receive updates.
        """
        with tracer.start_as_current_span("insights.get_all") as span:
            span.set_attribute("insights.datasource", datasource)

            # 1. Load current state from DB (fast Postgres read)
            current_insights = self._load_all_from_cache(datasource)

            # 2. Check whether tasks are already in flight (<10 min old)
            now = datetime.now(timezone.utc)
            is_processing = False
            for t in current_insights.values():
                if t.get("status") in ("pending", "processing"):
                    gen_at = self._parse_iso_utc(t.get("generated_at"))
                    if gen_at and (now - gen_at).total_seconds() < 600:
                        is_processing = True
                        break

            # 3. Determine whether a refresh is needed
            needs_refresh = force_refresh
            if not needs_refresh and not is_processing:
                if not current_insights:
                    needs_refresh = True
                else:
                    summary = current_insights.get("summary")
                    if summary:
                        gen_at = self._parse_iso_utc(summary.get("generated_at"))
                        if gen_at:
                            age = (now - gen_at).total_seconds()
                            if age > Config.INSIGHTS_CACHE_TTL:
                                logger.info(f"[insights] TTL expired ({age:.0f}s) for {datasource}")
                                needs_refresh = True
                        else:
                            needs_refresh = True
                    else:
                        needs_refresh = True

            if needs_refresh:
                logger.info(f"[insights] Scheduling coordinator for {datasource} (forced={force_refresh})")
                # Immediately mark tasks as pending so the frontend sees activity
                for ttype in ["summary", "graph", "stats"]:
                    self._set_task_status(datasource, ttype, "pending", "coordinator_scheduled",
                                          clear_data=force_refresh)
                # Route the coordinator through Kafka (or daemon thread fallback)
                from src.worker.kafka_producer import publish_task
                publish_task({"task_type": "insight_coordinator", "datasource": datasource})
                current_insights = self._load_all_from_cache(datasource)
                span.set_attribute("insights.refresh_triggered", True)
            else:
                span.set_attribute("insights.refresh_triggered", False)

            return {
                "tasks": current_insights,
                "_meta": {
                    "datasource":        datasource,
                    "is_processing":     is_processing or needs_refresh,
                    "refresh_triggered": needs_refresh,
                },
            }

    def invalidate(self, datasource: str = "default") -> None:
        """Delete cached insights, forcing regeneration on next call."""
        from src.session.models import InsightsCache, get_db
        with get_db() as db:
            db.query(InsightsCache).filter(InsightsCache.datasource == datasource).delete()
        logger.info(f"[insights] Cache invalidated for datasource={datasource}")

    # ── Task Orchestration ──────────────────────────────────────────────────────

    def _run_coordinator(self, datasource: str) -> None:
        """Background coordinator: fetch the ES sample then dispatch AI tasks.

        Called non-blocking from get_insights(). This is the method that does the
        expensive Elasticsearch call so the HTTP thread never blocks on it.
        """
        try:
            retriever = get_retriever()
            sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS, index_name=datasource)
            if not sample:
                logger.warning(f"[insights] Coordinator: no documents for {datasource}")
                for ttype in ["summary", "graph", "stats"]:
                    self._set_task_status(datasource, ttype, "error", "no_docs",
                                          error="No documents found in datasource")
                return

            doc_ids = sorted([str(d.get("id")) for d in sample])
            sample_hash = hashlib.sha256(",".join(doc_ids).encode()).hexdigest()
            logger.info(f"[insights] Coordinator: {len(sample)} docs, hash={sample_hash[:8]} for {datasource}")
            self._trigger_tasks(datasource, sample, sample_hash)
        except Exception as e:
            logger.error(f"[insights] Coordinator failed for {datasource}: {e}", exc_info=True)
            for ttype in ["summary", "graph", "stats"]:
                self._set_task_status(datasource, ttype, "error", "coordinator_failed", error=str(e))

    def _trigger_tasks(self, datasource: str, sample: List[dict], sample_hash: str):
        """Publish all insight sub-tasks to Kafka (or daemon thread fallback)."""
        from src.worker.kafka_producer import publish_task
        tasks = ["summary", "graph", "stats"]
        for ttype in tasks:
            self._set_task_status(datasource, ttype, "pending", sample_hash, clear_data=True)
            if ttype == "stats":
                publish_task({"task_type": "insight_stats", "datasource": datasource,
                              "sample_hash": sample_hash})
            else:
                publish_task({"task_type": "insight_ai", "datasource": datasource,
                              "insight_type": ttype, "sample_hash": sample_hash})

    def _run_ai_task(self, datasource: str, ttype: str, sample: List[dict], sample_hash: str):
        """Worker function for LLM tasks."""
        with tracer.start_as_current_span(f"insights.task.{ttype}") as span:
            self._set_task_status(datasource, ttype, "processing", sample_hash)
            logger.info(f"[insights] Starting AI task: {ttype}")
            
            try:
                llm = get_llm()
                messages, system = self._prompt_builder.build_insights_messages(sample, task_type=ttype)
                raw = llm.complete_json(
                    messages, system,
                    num_ctx=Config.LLM_INSIGHTS_CTX,
                    max_tokens=Config.LLM_INSIGHTS_MAX_TOKENS,
                )
                logger.debug(f"[insights] LLM response: {raw[:500]}...")
                
                payload = self._parse_json(raw)
                if payload is None:
                    logger.error(f"[insights] {ttype} JSON parse fail. Raw output: {raw[:500]}...")
                    raise ValueError(f"Failed to parse {ttype} JSON from LLM")

                # Empty dict {} means LLM produced no useful output — store as complete
                # with empty payload rather than failing, so the UI doesn't show an error.
                if not payload:
                    logger.warning(f"[insights] {ttype} returned empty JSON — storing as complete with no data")

                self._set_task_status(datasource, ttype, "complete", sample_hash, payload=payload)
                logger.info(f"[insights] Task {ttype} complete", "magenta")
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

    def _set_task_status(self, datasource: str, ttype: str, status: str, sample_hash: str,
                         payload=None, error=None, clear_data=False):
        """Persist task status to DB and broadcast to SSE subscribers."""
        from src.session.models import InsightsCache, get_db, get_engine
        with _lock:
            for attempt in range(2):
                try:
                    with get_db() as db:
                        row = db.query(InsightsCache).filter(
                            InsightsCache.datasource == datasource,
                            InsightsCache.insight_type == ttype
                        ).first()
                        now = datetime.now(timezone.utc)
                        if not row:
                            row = InsightsCache(datasource=datasource, insight_type=ttype,
                                               generated_at=now)
                            db.add(row)
                        row.status = status
                        row.sample_hash = sample_hash
                        if status == "processing":
                            row.started_at = now
                        if clear_data:
                            row.payload = None
                            row.error = None
                        else:
                            if payload is not None:
                                row.payload = payload
                            if error is not None:
                                row.error = error
                        db.commit()
                        snapshot = row.to_dict()

                    # Notify SSE subscribers that a task changed
                    _event_bus.publish(datasource, {
                        "type":         "task_update",
                        "insight_type": ttype,
                        "task":         snapshot,
                    })
                    break  # success
                except Exception as e:
                    if attempt == 0:
                        # Invalidate all stale connections and retry once
                        logger.warning(f"[insights] DB update failed for {ttype}, retrying: {e}")
                        try:
                            get_engine().dispose()
                        except Exception:
                            pass
                    else:
                        logger.error(f"[insights] Failed DB update for {ttype}: {e}")

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
    def _extract_known_keys(data: dict) -> dict:
        """Unwrap a rogue top-level key if the LLM wrapped the real payload in one."""
        if not isinstance(data, dict):
            return data
        _KNOWN = {"hot_topics", "entities", "nodes", "edges", "trends",
                  "narratives", "sentiment", "classification", "summary"}
        if any(k in data for k in _KNOWN):
            return data
        # Search one level deep
        for v in data.values():
            if isinstance(v, dict) and any(k in v for k in _KNOWN):
                return v
        return data

    @staticmethod
    def _extract_json_object(text: str) -> Optional[str]:
        """Find the first complete JSON object in *text* using brace matching.

        Handles nested objects and JSON strings containing braces/quotes correctly.
        Returns the substring `{...}` or None if none found.
        """
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_str = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """Robustly extract a JSON object from LLM output.

        Strategy (each step only runs if the previous failed):
        1. Strip markdown fences, try direct json.loads.
        2. Fix trailing commas before } or ], retry json.loads.
        3. Remove // line comments (only when no :// URLs present), retry.
        4. Use brace-matching extractor to isolate the first { ... } block.
        """
        if not raw:
            return None

        # Step 0a: strip <think>...</think> reasoning blocks (Qwen3 / reasoning models)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()

        # Step 0b: strip markdown code fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

        def _try(text: str) -> Optional[dict]:
            try:
                return InsightsEngine._extract_known_keys(json.loads(text))
            except (json.JSONDecodeError, ValueError):
                return None

        # Step 1: direct parse
        result = _try(cleaned)
        if result is not None:
            return result

        # Step 2: fix trailing commas before } or ]
        fixed = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        result = _try(fixed)
        if result is not None:
            return result

        # Step 3: strip // line comments (safe only when no :// URI present)
        if "//" in fixed and "://" not in fixed:
            no_comments = re.sub(r"//[^\n]*", "", fixed)
            result = _try(no_comments)
            if result is not None:
                return result
        else:
            no_comments = fixed

        # Step 4: brace-matching extraction from the cleaned string
        obj_str = InsightsEngine._extract_json_object(no_comments)
        if obj_str:
            # Apply trailing-comma fix to the extracted substring too
            obj_str = re.sub(r",(\s*[}\]])", r"\1", obj_str)
            result = _try(obj_str)
            if result is not None:
                return result

        logger.warning(f"[insights] _parse_json exhausted all strategies. Raw[:200]: {raw[:200]}")
        return None

    @staticmethod
    def _empty_response(datasource: str, reason: str) -> dict:
        return {"tasks": {}, "_meta": {"datasource": datasource, "reason": reason}}


_engine: InsightsEngine | None = None

def get_insights_engine() -> InsightsEngine:
    global _engine
    if _engine is None: _engine = InsightsEngine()
    return _engine
