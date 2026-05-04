"""QSINT RAG — entry point.

Starts the HTTP API using the QF Framework's FrameworkApp.
No Kafka ETL — RAG is pure request/response + SSE streaming.
"""

# GEVENT MONKEY PATCHING MUST BE FIRST
try:
    from gevent import monkey
    monkey.patch_all()
    try:
        import psycogreen.gevent
        psycogreen.gevent.patch_psycopg()
    except ImportError:
        pass
except ImportError:
    pass

import os
import signal
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv()

from src.config import Config
from framework.app import FrameworkApp, FrameworkSettings
from framework.commons.logger import logger

# Suppress Werkzeug's per-request access log lines (127.0.0.1 - - GET ...)
import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    sig_name = signal.Signals(signum).name
    logger.info(f"[SHUTDOWN] Received {sig_name} — initiating graceful shutdown")
    sys.exit(0)


def _recover_dangling_tasks() -> None:
    """On every startup, requeue tasks left in pending/processing by a previous run.

    Kafka messages for these tasks were already committed by the previous consumer
    session and will never be redelivered — we must republish them explicitly.

    Insights  → reset to pending + republish the exact task type (not the full
                coordinator) so already-complete sibling tasks are not overwritten.
    Enrichment pending   → fetch text from ES and republish enrich_doc.
    Enrichment processing → mark error (text not stored; user retries via UI).
    """
    try:
        from src.insights.models import InsightsCache
        from src.enrichment.models import DocumentEnrichment
        from src.core.db import get_db
        from src.tasking.producer import publish_task

        with get_db() as db:
            # ── Insights ──────────────────────────────────────────────────────
            stuck_insights = db.query(InsightsCache).filter(
                InsightsCache.status.in_(["pending", "processing"])
            ).all()
            insight_tasks = [(r.datasource, r.insight_type, r.sample_hash or "") for r in stuck_insights]
            for row in stuck_insights:
                row.status = "pending"
                row.error  = None
            if stuck_insights:
                db.commit()
                for ds, itype, sample_hash in insight_tasks:
                    if itype in ("summary", "graph"):
                        publish_task({"task_type": "insight_ai", "datasource": ds,
                                      "insight_type": itype, "sample_hash": sample_hash})
                    elif itype == "stats":
                        publish_task({"task_type": "insight_stats", "datasource": ds,
                                      "sample_hash": sample_hash})
                logger.info(f"[QSINT-RAG] Requeued {len(stuck_insights)} insight task(s): "
                            + ", ".join(f"{ds}/{t}" for ds, t, _ in insight_tasks))

            # ── Enrichment: processing → error (text not stored) ──────────────
            stuck_enrich = db.query(DocumentEnrichment).filter_by(status="processing").all()
            for row in stuck_enrich:
                row.status = "error"
                row.error  = "Interrupted by app restart — please retry"
            if stuck_enrich:
                db.commit()
                logger.info(f"[QSINT-RAG] Marked {len(stuck_enrich)} in-progress enrichment(s) as error")

            # ── Enrichment: pending → re-fetch text from ES and republish ─────
            pending_enrich = [(r.doc_id, r.datasource)
                              for r in db.query(DocumentEnrichment).filter_by(status="pending").all()]

        # ── Uploads: parsing/indexing → republish ─────────────────────────
        # The original file is on disk and ES upserts on stable _id, so
        # replaying ingest_file (parsing) or ingest_continue (indexing) is
        # safe and idempotent.
        try:
            from src.ingestion.models import UploadedFile
            with get_db() as db:
                stuck_uploads = db.query(UploadedFile).filter(
                    UploadedFile.status.in_(["parsing", "indexing"])
                ).all()
                upload_replays = [(u.id, u.investigation_id, u.status) for u in stuck_uploads]
                # Reset to a clean state — parsing rows go back to pending so
                # run_parse can re-pick a handler; indexing rows stay so
                # run_index can resume from indexed_count.
                for u in stuck_uploads:
                    if u.status == "parsing":
                        u.status = "pending"
                if stuck_uploads:
                    db.commit()
            for fid, ds, prev_status in upload_replays:
                ttype = "ingest_continue" if prev_status == "indexing" else "ingest_file"
                publish_task({
                    "task_type": ttype, "file_id": fid,
                    "investigation_id": ds, "datasource": ds,
                })
            if upload_replays:
                logger.info(f"[QSINT-RAG] Requeued {len(upload_replays)} upload task(s)")

            # Files that finished indexing but never finished embedding —
            # republish embed_file so their hybrid status converges.
            with get_db() as db:
                stale_embed = db.query(UploadedFile).filter(
                    UploadedFile.status == "complete",
                    UploadedFile.vectors_ready.is_(False),
                    UploadedFile.indexed_count > 0,
                ).all()
                embed_replays = [(u.id, u.investigation_id) for u in stale_embed]
            for fid, ds in embed_replays:
                publish_task({
                    "task_type": "embed_file", "file_id": fid,
                    "investigation_id": ds, "datasource": ds,
                })
            if embed_replays:
                logger.info(f"[QSINT-RAG] Requeued {len(embed_replays)} embed_file task(s)")
        except Exception as up_err:
            logger.warning(f"[QSINT-RAG] Upload recovery failed: {up_err}")

        if pending_enrich:
            from src.retrieval.es_client import ESClient
            client = ESClient()
            requeued, missing = 0, 0
            for doc_id, datasource in pending_enrich:
                try:
                    text = client.get_document_text(doc_id=doc_id, index_name=datasource)
                    if text:
                        publish_task({"task_type": "enrich_doc", "datasource": datasource,
                                      "doc_id": doc_id, "text": text})
                        requeued += 1
                    else:
                        with get_db() as db2:
                            row = db2.query(DocumentEnrichment).filter_by(
                                doc_id=doc_id, datasource=datasource).first()
                            if row:
                                row.status = "error"
                                row.error  = "Document text not found after restart"
                                db2.commit()
                        missing += 1
                except Exception as ex:
                    logger.warning(f"[QSINT-RAG] Could not requeue enrichment {doc_id}: {ex}")
            logger.info(f"[QSINT-RAG] Enrichment recovery: requeued={requeued} missing={missing}"
                        f" (of {len(pending_enrich)} pending)")

    except Exception as e:
        logger.warning(f"[QSINT-RAG] Task recovery failed (non-fatal): {e}")


def main():
    from src.llm.client import get_llm
    llm = get_llm()
    logger.info(
        f"[QSINT-RAG] Starting — dev_mode={Config.DEV_MODE} "
        f"datasource={Config.DATASOURCE_TYPE} llm_model={llm.model_name} "
        f"api_port={Config.API_PORT} llm_parallel={Config.LLM_PARALLEL}",
        "magenta"
    )

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Initialize Postgres tables on startup
    from src.core.db import init_db
    try:
        init_db()
        logger.info("[QSINT-RAG] Database tables initialized")
    except Exception as e:
        logger.warning(f"[QSINT-RAG] Could not initialize DB (will retry on first use): {e}")

    # Recover tasks that were interrupted mid-processing by a previous crash/restart.
    _recover_dangling_tasks()

    # Eager-import ingestion task handlers so they register via @register()
    # before the consumer starts pulling messages.
    try:
        import src.ingestion.tasks  # noqa: F401
        logger.info("[QSINT-RAG] Ingestion task handlers registered")
    except Exception as e:
        logger.warning(f"[QSINT-RAG] Ingestion task handler import failed: {e}")

    # Start Kafka consumer worker
    from src.tasking.consumer import start_consumer
    try:
        start_consumer()
        logger.info("[QSINT-RAG] Kafka consumer started")
    except Exception as e:
        logger.warning(f"[QSINT-RAG] Kafka consumer not started (fallback to threads): {e}")

    settings = FrameworkSettings(
        enable_etl=False,          # No Kafka — RAG is HTTP only
        enable_api=True,
        enable_dynamic_endpoints=True,

        api_host="0.0.0.0",
        api_port=Config.API_PORT,
        api_version="1.0",
        api_title="QSINT RAG API",
        api_description="Retrieval-Augmented Generation for QSINT intelligence data",

        endpoint_json_path="maps/endpoint.json",

        enable_tracing=Config.ENABLE_TRACING,
        otlp_endpoint=Config.OTLP_ENDPOINT,
        service_name="qsint-rag",
    )

    fw = FrameworkApp(settings, app_root=BASE_DIR)
    handles = fw.run()

    if handles.app:
        logger.info(f"[QSINT-RAG] API listening on {settings.api_host}:{settings.api_port}")
        try:
            handles.app.run(
                host=settings.api_host,
                port=settings.api_port,
                debug=False,
            )
        except (KeyboardInterrupt, SystemExit):
            logger.info("[QSINT-RAG] Exiting")


if __name__ == "__main__":
    main()
