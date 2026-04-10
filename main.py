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
    """Reset tasks stuck in 'processing' from a previous crash or restart.

    - InsightsCache: reset to 'pending' and republish coordinator tasks so they
      are picked up by the Kafka worker automatically.
    - DocumentEnrichment: reset to 'error' (document text is not stored in the DB,
      so we can't requeue automatically — the user can retry via the UI).
    """
    try:
        from src.session.models import InsightsCache, DocumentEnrichment, get_db
        from src.worker.kafka_producer import publish_task

        with get_db() as db:
            # ── Insights ──────────────────────────────────────────────────────
            stuck_insights = db.query(InsightsCache).filter_by(status="processing").all()
            requeued_ds: set[str] = set()
            for row in stuck_insights:
                row.status = "pending"
                row.error = None
                requeued_ds.add(row.datasource)
            if stuck_insights:
                db.commit()
                for ds in requeued_ds:
                    publish_task({"task_type": "insight_coordinator", "datasource": ds})
                logger.info(
                    f"[QSINT-RAG] Requeued {len(stuck_insights)} dangling insight task(s) "
                    f"across datasource(s): {', '.join(requeued_ds)}"
                )

            # ── Enrichment ────────────────────────────────────────────────────
            stuck_enrichments = db.query(DocumentEnrichment).filter_by(status="processing").all()
            for row in stuck_enrichments:
                row.status = "error"
                row.error = "Interrupted by app restart — please retry"
            if stuck_enrichments:
                db.commit()
                logger.info(
                    f"[QSINT-RAG] Marked {len(stuck_enrichments)} dangling enrichment task(s) "
                    f"as error (retry via UI)"
                )

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
