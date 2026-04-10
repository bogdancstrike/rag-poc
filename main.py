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


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    sig_name = signal.Signals(signum).name
    logger.info(f"[SHUTDOWN] Received {sig_name} — initiating graceful shutdown")
    sys.exit(0)


def main():
    logger.info(
        f"[QSINT-RAG] Starting — dev_mode={Config.DEV_MODE} "
        f"datasource={Config.DATASOURCE_TYPE} "
        f"llm_model={Config.LLM_MODEL} "
        f"api_port={Config.API_PORT}"
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
