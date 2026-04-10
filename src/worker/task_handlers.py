"""Task handlers dispatched by the Kafka consumer.

Each function receives a task dict and performs all the work (LLM calls, DB
updates, SSE notifications). Handlers are pure — no Kafka dependency.
"""
import hashlib
from datetime import datetime, timezone

from framework.commons.logger import logger
from src.config import Config


def dispatch_task(task: dict) -> None:
    """Route a task dict to the correct handler. Called by the Kafka consumer."""
    ttype = task.get("task_type", "")
    ds    = task.get("datasource", "?")
    t0    = datetime.now(timezone.utc)
    logger.info(f"[worker] ▶ start task_type={ttype} ds={ds}", "green")
    try:
        if ttype == "insight_coordinator":
            handle_insight_coordinator(task)
        elif ttype == "insight_ai":
            handle_insight_ai(task)
        elif ttype == "insight_stats":
            handle_insight_stats(task)
        elif ttype == "enrich_doc":
            handle_enrich_doc(task)
        elif ttype == "enrich_field":
            handle_enrich_field(task)
        else:
            logger.warning(f"[worker] Unknown task_type: {ttype!r}")
            return
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        logger.info(f"[worker] ✓ done  task_type={ttype} ds={ds} elapsed={elapsed:.1f}s", "magenta")
    except Exception as e:
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        logger.error(f"[worker] ✗ fail  task_type={ttype} ds={ds} elapsed={elapsed:.1f}s err={e}", exc_info=True)


# ── Insight tasks ──────────────────────────────────────────────────────────────

def handle_insight_coordinator(task: dict) -> None:
    """Fetch ES sample, compute hash, fan-out sub-tasks."""
    datasource = task["datasource"]
    try:
        from src.rag.retriever import get_retriever
        from src.rag.insights_engine import get_insights_engine
        from src.worker.kafka_producer import publish_task

        retriever = get_retriever()
        sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS, index_name=datasource)
        if not sample:
            logger.warning(f"[worker] No docs for coordinator: {datasource}")
            engine = get_insights_engine()
            for t in ("summary", "graph", "stats"):
                engine._set_task_status(datasource, t, "error", "no_docs",
                                        error="No documents found in datasource")
            return

        doc_ids = sorted(str(d.get("id", "")) for d in sample)
        sample_hash = hashlib.sha256(",".join(doc_ids).encode()).hexdigest()
        logger.info(f"[worker] Coordinator: {len(sample)} docs hash={sample_hash[:8]} ds={datasource}")

        publish_task({"task_type": "insight_stats", "datasource": datasource, "sample_hash": sample_hash})
        for insight_type in ("summary", "graph"):
            publish_task({"task_type": "insight_ai", "datasource": datasource,
                          "insight_type": insight_type, "sample_hash": sample_hash})
    except Exception as e:
        logger.error(f"[worker] Coordinator failed ds={datasource}: {e}", exc_info=True)


def handle_insight_ai(task: dict) -> None:
    """Run LLM for one insight type (summary / graph)."""
    datasource = task["datasource"]
    insight_type = task["insight_type"]
    sample_hash = task.get("sample_hash", "unknown")

    from src.rag.retriever import get_retriever
    from src.rag.insights_engine import get_insights_engine

    retriever = get_retriever()
    sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS, index_name=datasource)
    engine = get_insights_engine()
    engine._run_ai_task(datasource, insight_type, sample or [], sample_hash)


def handle_insight_stats(task: dict) -> None:
    """Run Elasticsearch aggregations for the stats insight."""
    from src.rag.insights_engine import get_insights_engine
    engine = get_insights_engine()
    engine._run_stats_task(task["datasource"], task.get("sample_hash", "unknown"))


# ── Document enrichment tasks ──────────────────────────────────────────────────

def handle_enrich_doc(task: dict) -> None:
    """Full document enrichment (all fields via LLM + regex + geocoding)."""
    from src.api.endpoints import _run_enrichment_background
    _run_enrichment_background(task["datasource"], task["doc_id"], task["text"])


def handle_enrich_field(task: dict) -> None:
    """Single-field re-enrichment."""
    datasource = task["datasource"]
    doc_id = task["doc_id"]
    text = task["text"]
    field = task["field"]

    from src.session.models import DocumentEnrichment, get_db
    from src.rag.llm_client import get_llm
    from src.rag.prompt_builder import PromptBuilder
    from src.rag.insights_engine import InsightsEngine
    from src.api.endpoints import _extract_iocs, _geocode_location

    try:
        partial: dict = {}

        if field == "iocs":
            partial = {"iocs": _extract_iocs(text)}

        elif field == "locations":
            builder = PromptBuilder()
            msgs, sys_ = builder.build_field_enrichment_messages(text[:3000], "locations")
            parsed = InsightsEngine._parse_json(get_llm().complete_json(msgs, sys_)) or {}
            geocoded = []
            for name in (parsed.get("locations") or [])[:20]:
                geo = _geocode_location(name)
                geocoded.append(geo or {"name": name, "lat": None, "lon": None, "display_name": name})
            partial = {"locations": geocoded}

        elif field == "translation":
            builder = PromptBuilder()
            msgs, sys_ = builder.build_translation_messages(text[:4000])
            parsed = InsightsEngine._parse_json(get_llm().complete_json(msgs, sys_)) or {}
            partial = {"translation": parsed.get("text", "")}

        else:
            builder = PromptBuilder()
            msgs, sys_ = builder.build_field_enrichment_messages(text[:3000], field)
            parsed = InsightsEngine._parse_json(get_llm().complete_json(msgs, sys_)) or {}
            if not parsed:
                raise ValueError(f"Unparseable JSON from LLM for field={field}")
            partial = parsed

        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if not row:
                row = DocumentEnrichment(doc_id=doc_id, datasource=datasource,
                                         status="complete", payload={})
                db.add(row)
            existing = dict(row.payload or {})
            existing.update(partial)
            row.payload = existing
            row.status = "complete"
            row.error = None
            db.commit()
            logger.info(f"[worker] Field '{field}' updated doc_id={doc_id}")

    except Exception as e:
        logger.error(f"[worker] enrich_field '{field}' failed doc_id={doc_id}: {e}", exc_info=True)
        try:
            with get_db() as db:
                row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                if row:
                    row.error = str(e)
                    db.commit()
        except Exception:
            pass
