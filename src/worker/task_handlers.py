"""Task handlers dispatched by the Kafka consumer.

Each function receives a task dict and performs all the work (LLM calls, DB
updates, SSE notifications). Handlers are pure — no Kafka dependency.
"""
import hashlib
import json
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
        mark_task_error(task, str(e))


def mark_task_error(task: dict, error_msg: str) -> None:
    """Write 'error' status to DB for a failed or timed-out task."""
    ttype = task.get("task_type", "")
    ds    = task.get("datasource", "?")
    try:
        if ttype in ("insight_ai", "insight_stats"):
            from src.rag.insights_engine import get_insights_engine
            engine = get_insights_engine()
            insight_type = task.get("insight_type", ttype)
            engine._set_task_status(ds, insight_type, "error",
                                    task.get("sample_hash", ""), error=error_msg)
        elif ttype in ("enrich_doc", "enrich_field"):
            from src.session.models import DocumentEnrichment, get_db
            with get_db() as db:
                row = db.query(DocumentEnrichment).filter_by(
                    doc_id=task.get("doc_id"), datasource=ds
                ).first()
                if row:
                    row.status = "error"
                    row.error  = error_msg
                    db.commit()
    except Exception as e:
        logger.error(f"[worker] Failed to mark error in DB: {e}")


# ── Insight tasks ──────────────────────────────────────────────────────────────

def handle_insight_coordinator(task: dict) -> None:
    """Fetch ES sample, compute hash, fan-out sub-tasks."""
    datasource = task["datasource"]
    all_tasks = [
        "trending_signals", "relationship_network", "active_narratives", "hot_topics_sentiment",
        "corpus_statistics", "top_regions", "top_entities", "top_platforms"
    ]
    from src.rag.insights_engine import get_insights_engine
    engine = get_insights_engine()
    engine.run_all_insights(datasource, force=task.get("force", False))


def handle_insight_ai(task: dict) -> None:
    """Run a single LLM-based insight task (hot topics, narratives, etc)."""
    datasource   = task["datasource"]
    insight_type = task["insight_type"]
    sample_hash  = task["sample_hash"]
    
    from src.rag.insights_engine import get_insights_engine
    from src.rag.retriever import get_retriever
    
    engine = get_insights_engine()
    retriever = get_retriever()
    
    # We must fetch the same sample used for hashing
    sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS, index_name=datasource)
    
    # Logic is internal to InsightsEngine
    engine._run_ai_task(datasource, insight_type, sample, sample_hash)


def handle_insight_stats(task: dict) -> None:
    """Run a single statistics-based insight task (charts, distributions)."""
    datasource   = task["datasource"]
    insight_type = task["insight_type"]
    sample_hash  = task["sample_hash"]
    
    from src.rag.insights_engine import get_insights_engine
    engine = get_insights_engine()
    engine._run_stats_task(datasource, insight_type, sample_hash)


def handle_create_investigation(task: dict) -> None:
    """Background task: create a new ES index for an investigation and populate it.

    1. Create the destination ES index
    2. For each linked saved search, scroll matching docs from source indices
       and bulk-copy them into the investigation index (deduplication via ES _id)
    3. Update DB status to 'ready'
    """
    inv_id     = task["investigation_id"]
    index_name = task["index_name"]
    search_ids = task.get("search_ids") or []

    from src.session.session_service import get_saved_search, update_investigation_status
    from src.datasource.es_client import ESClient

    try:
        es = ESClient()

        # 1. Create the investigation index
        es.create_index(index_name)

        # 2. For each saved search, copy matching docs via scroll+bulk
        total_copied = 0

        for sid in search_ids:
            search = get_saved_search(sid)
            if not search:
                logger.warning(f"[investigation] Search {sid} not found, skipping")
                continue

            query_str = search.get("query", "") or ""
            filters   = search.get("filters") or {}

            # Build ES query from saved search definition
            filter_clauses = []
            if filters.get("sentiment"):
                filter_clauses.append({"term": {"sentiment.keyword": filters["sentiment"]}})
            if filters.get("date_from") or filters.get("date_to"):
                range_clause: dict = {}
                if filters.get("date_from"):
                    range_clause["gte"] = filters["date_from"]
                if filters.get("date_to"):
                    range_clause["lte"] = filters["date_to"]
                filter_clauses.append({"range": {"created_at": range_clause}})

            q = query_str[:512]
            text_query = (
                {"query_string": {"query": q, "default_operator": "AND"}}
                if q
                else {"match_all": {}}
            )
            query_body = (
                {"query": {"bool": {"must": text_query, "filter": filter_clauses}}}
                if filter_clauses
                else {"query": text_query}
            )

            # Use index_patterns from filters or search all qsint indices.
            # Config.ES_INDEX may not exist (seeded data lives in *_cyber, *_geopolitics, etc.)
            source_indices = filters.get("index_patterns") or ["qsint_docs*"]

            copied = es.copy_documents(
                source_indices=source_indices,
                query_body=query_body,
                dest_index=index_name,
            )
            total_copied += copied
            logger.info(f"[investigation] Copied {copied} docs from search {sid}")

        # 3. Update status
        update_investigation_status(
            investigation_id=inv_id,
            status="ready",
            doc_count=total_copied,
        )
        logger.info(f"[investigation] Ready: {inv_id} index={index_name} docs={total_copied}", "magenta")

    except Exception as e:
        logger.error(f"[investigation] Failed to create {inv_id}: {e}", exc_info=True)
        update_investigation_status(
            investigation_id=inv_id,
            status="error",
            error_msg=str(e),
        )
        raise


# ── Enrichment tasks ───────────────────────────────────────────────────────────

def handle_enrich_doc(task: dict) -> None:
    """Enrich a single document (full pipeline)."""
    datasource = task["datasource"]
    doc_id     = task["doc_id"]
    text       = task.get("text", "")

    # We reuse the existing logic in api.endpoints
    from src.api.endpoints import _run_enrichment_background
    _run_enrichment_background(datasource, doc_id, text)


def handle_enrich_field(task: dict) -> None:
    """Enrich a single field of a document."""
    datasource = task["datasource"]
    doc_id     = task["doc_id"]
    field      = task["field"]
    text       = task.get("text", "")

    from src.session.models import DocumentEnrichment, get_db

    try:
        # IOC extraction uses regex, not LLM
        if field == "iocs":
            from src.api.endpoints import _extract_iocs
            payload = {"iocs": _extract_iocs(text)}
        else:
            from src.rag.llm_client import get_llm
            from src.rag.prompt_builder import PromptBuilder
            from src.rag.insights_engine import InsightsEngine

            builder = PromptBuilder()
            llm = get_llm()
            messages, system = builder.build_field_enrichment_messages(text[:3000], field)
            raw = llm.complete_json(messages, system)
            payload = InsightsEngine._parse_json(raw)

        if payload is None:
            raise ValueError(f"Failed to parse field enrichment JSON for {field}")

        # Update specific field in existing payload
        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if not row:
                row = DocumentEnrichment(doc_id=doc_id, datasource=datasource, status="processing", payload={})
                db.add(row)
            
            curr = row.payload or {}
            # Update the field (handle nested graph/timeline if needed)
            if field in payload:
                curr[field] = payload[field]
            else:
                # LLM might have returned just the value or a different key
                # Take first key that isn't empty
                for k, v in payload.items():
                    if v:
                        curr[field] = v
                        break
            
            row.payload = curr
            row.status = "complete"
            row.error = None
            db.commit()
            logger.info(f"[worker] Field '{field}' updated doc_id={doc_id}")

    except Exception as e:
        logger.error(f"[worker] enrich_field '{field}' failed doc_id={doc_id}: {e}", exc_info=True)
        # Re-raise so dispatch_task handles DB marking
        raise
