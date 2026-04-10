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
    """Requeue tasks left in 'pending' or 'processing' by a previous crash/restart.

    'pending' tasks had their Kafka messages already committed by the previous
    consumer session, so they will never be delivered again — we must republish.
    'processing' tasks were mid-execution when the process died.

    - InsightsCache (both states): reset to 'pending' + republish coordinator.
    - DocumentEnrichment processing: reset to 'error' (text not in DB; retry via UI).
    - DocumentEnrichment pending: fetch text from ES and republish to Kafka.
    """
    try:
        from src.session.models import InsightsCache, DocumentEnrichment, get_db
        from src.worker.kafka_producer import publish_task

        with get_db() as db:
            # ── Insights: requeue pending + processing ─────────────────────
            stuck = db.query(InsightsCache).filter(
                InsightsCache.status.in_(["pending", "processing"])
            ).all()
            requeue_ds: set[str] = set()
            for row in stuck:
                row.status = "pending"
                row.error = None
                requeue_ds.add(row.datasource)
            if stuck:
                db.commit()
                for ds in requeue_ds:
                    publish_task({"task_type": "insight_coordinator", "datasource": ds})
                logger.info(
                    f"[QSINT-RAG] Requeued {len(stuck)} insight task(s) "
                    f"across: {', '.join(requeue_ds)}"
                )

            # ── Enrichment processing: mark error (no text stored) ─────────
            processing = db.query(DocumentEnrichment).filter_by(status="processing").all()
            for row in processing:
                row.status = "error"
                row.error = "Interrupted by app restart — please retry"
            if processing:
                db.commit()
                logger.info(
                    f"[QSINT-RAG] Marked {len(processing)} in-progress enrichment(s) as error"
                )

            # ── Enrichment pending: fetch text from ES and republish ────────
            pending = db.query(DocumentEnrichment).filter_by(status="pending").all()
            pending_rows = [(r.doc_id, r.datasource) for r in pending]

        if pending_rows:
            from src.datasource.es_client import ESClient
            client = ESClient()
            requeued = 0
            for doc_id, datasource in pending_rows:
                try:
                    docs, _ = client.get_documents(
                        index_name=datasource, offset=0, limit=1, id_filter=[doc_id]
                    )
                    text = docs[0].get("text", "") if docs else ""
                    if text:
                        publish_task({
                            "task_type": "enrich_doc",
                            "datasource": datasource,
                            "doc_id": doc_id,
                            "text": text,
                        })
                        requeued += 1
                    else:
                        # No text found — mark as error so it doesn't dangle
                        with get_db() as db:
                            row = db.query(DocumentEnrichment).filter_by(
                                doc_id=doc_id, datasource=datasource
                            ).first()
                            if row:
                                row.status = "error"
                                row.error = "Document text not found after restart"
                                db.commit()
                except Exception as e:
                    logger.warning(f"[QSINT-RAG] Could not requeue enrichment {doc_id}: {e}")
            if requeued:
                logger.info(f"[QSINT-RAG] Requeued {requeued}/{len(pending_rows)} pending enrichment(s)")

    except Exception as e:
        logger.warning(f"[QSINT-RAG] Task recovery failed (non-fatal): {e}")


def main():
    logger.info(
        f"[QSINT-RAG] Starting — dev_mode={Config.DEV_MODE} "
        f"datasource={Config.DATASOURCE_TYPE} "
        f"llm_model={Config.LLM_MODEL} "
        f"api_port={Config.API_PORT} "
        f"llm_parallel={Config.LLM_PARALLEL}"
    )

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Initialize Postgres tables on startup
    from src.session.models import init_db
    try:
        init_db()
        logger.info("[QSINT-RAG] Database tables initialized")
    except Exception as e:
        logger.warning(f"[QSINT-RAG] Could not initialize DB (will retry on first use): {e}")

    # Recover tasks that were interrupted mid-processing by a previous crash/restart.
    _recover_dangling_tasks()

    # Start Kafka consumer worker
    from src.worker.kafka_consumer import start_consumer
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
                debug=Config.DEV_MODE,
            )
        except (KeyboardInterrupt, SystemExit):
            logger.info("[QSINT-RAG] Exiting")


if __name__ == "__main__":
    main()
