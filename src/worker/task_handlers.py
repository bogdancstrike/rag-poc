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
        elif ttype == "create_investigation":
            handle_create_investigation(task)
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


def handle_create_investigation(task: dict) -> None:
    """Create an ES index for an investigation and populate it from saved searches.

    task = {
        "task_type":        "create_investigation",
        "investigation_id": str,
        "index_name":       str,
        "search_ids":       [str, ...],
    }
    """
    from src.session.session_service import (
        get_investigation, update_investigation_status, get_saved_search,
    )
    from src.datasource.es_client import ESClient

    investigation_id = task["investigation_id"]
    index_name       = task["index_name"]
    search_ids       = task.get("search_ids") or []

    logger.info(f"[worker] create_investigation id={investigation_id} index={index_name} "
                f"searches={len(search_ids)}")

    try:
        client = ESClient()

        # 1. Create the destination index
        client.create_index(index_name)

        # 2. For each saved search, build ES query and copy matching docs
        total_copied = 0

        if not search_ids:
            # No searches attached — create empty investigation immediately
            update_investigation_status(investigation_id, "ready", doc_count=0)
            return

        for sid in search_ids:
            search = get_saved_search(sid)
            if not search:
                logger.warning(f"[worker] Saved search {sid} not found, skipping")
                continue

            q_text  = (search.get("query") or "").strip()
            filters = search.get("filters") or {}

            # Determine source indices
            index_patterns = filters.get("index_patterns") or []
            source_indices = index_patterns if index_patterns else ["qsint_docs*"]

            # Build ES query from saved search
            es_filters = []
            if filters.get("sentiment"):
                es_filters.append({"term": {"sentiment.keyword": filters["sentiment"]}})
            if filters.get("date_from") or filters.get("date_to"):
                range_clause: dict = {}
                if filters.get("date_from"):
                    range_clause["gte"] = filters["date_from"]
                if filters.get("date_to"):
                    range_clause["lte"] = filters["date_to"]
                es_filters.append({"range": {"created_at": range_clause}})

            if q_text:
                text_query = {
                    "query_string": {
                        "query":            q_text[:512],
                        "default_operator": "AND",
                    }
                }
            else:
                text_query = {"match_all": {}}

            query_body = {
                "query": (
                    {"bool": {"must": text_query, "filter": es_filters}}
                    if es_filters
                    else text_query
                )
            }

            try:
                copied = client.copy_documents(
                    source_indices=source_indices,
                    query_body=query_body,
                    dest_index=index_name,
                )
                total_copied += copied
                logger.info(f"[worker] Search {sid}: copied {copied} docs → {index_name}")
            except Exception as e:
                logger.error(f"[worker] Search {sid} copy failed: {e}", exc_info=True)

        update_investigation_status(investigation_id, "ready", doc_count=total_copied)
        logger.info(f"[worker] Investigation {investigation_id} ready, total={total_copied} docs")

    except Exception as e:
        logger.error(f"[worker] create_investigation failed id={investigation_id}: {e}", exc_info=True)
        try:
            update_investigation_status(investigation_id, "error", error_msg=str(e))
        except Exception:
            pass
        raise


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
