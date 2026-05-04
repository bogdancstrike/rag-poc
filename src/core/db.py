"""Database infrastructure — engine, session factory, context manager, schema init."""
from contextlib import contextmanager

from sqlalchemy import (
    Column, String, Integer, Text, DateTime,
    create_engine, Index, text, event, exc as sa_exc,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config import Config
from framework.commons.logger import logger

Base = declarative_base()

_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        kwargs = {"pool_pre_ping": True}
        # Pool sizing only applies to real RDBMS pools; SQLite uses
        # SingletonThreadPool which rejects these kwargs (test harness path).
        if not Config.DATABASE_URL.startswith("sqlite"):
            kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_recycle": 300})
        _engine = create_engine(Config.DATABASE_URL, **kwargs)

        @event.listens_for(_engine, "checkout")
        def _validate_connection(dbapi_conn, conn_record, conn_proxy):
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            except Exception:
                raise sa_exc.DisconnectionError()
            finally:
                cursor.close()

    return _engine


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionFactory


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    conn.execute(text(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
    ))


def init_db():
    """Create all tables and apply incremental schema migrations.

    Imports all domain model modules first so their tables are registered with Base.
    """
    # Import all domain models so SQLAlchemy knows about their tables
    import src.chat.models          # noqa: F401 – Session, Message
    import src.insights.models      # noqa: F401 – InsightsCache
    import src.enrichment.models    # noqa: F401 – DocumentEnrichment
    import src.investigations.models  # noqa: F401 – Investigation, SavedSearch, etc.
    import src.ingestion.models       # noqa: F401 – UploadedFile, ParserProfile

    engine = get_engine()
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # Legacy migration: drop old single-column insights table
    if "rag_insights_cache" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("rag_insights_cache")]
        if "insight_type" not in cols:
            logger.warning("[db] Old rag_insights_cache schema — dropping for rebuild")
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS rag_insights_cache CASCADE"))
                conn.commit()

    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        if "rag_insights_cache" in inspector.get_table_names():
            ic_cols = [c["name"] for c in inspector.get_columns("rag_insights_cache")]
            if "started_at" not in ic_cols:
                _add_column_if_missing(conn, "rag_insights_cache", "started_at", "TIMESTAMP")
            if "updated_at" not in ic_cols:
                _add_column_if_missing(conn, "rag_insights_cache", "updated_at",
                                       "TIMESTAMP NOT NULL DEFAULT NOW()")
            if "retry_count" not in ic_cols:
                _add_column_if_missing(conn, "rag_insights_cache", "retry_count",
                                       "INTEGER NOT NULL DEFAULT 0")

        if "rag_document_enrichment" in existing_tables:
            de_cols = [c["name"] for c in inspector.get_columns("rag_document_enrichment")]
            if "started_at" not in de_cols:
                _add_column_if_missing(conn, "rag_document_enrichment", "started_at", "TIMESTAMP")
            if "updated_at" not in de_cols:
                _add_column_if_missing(conn, "rag_document_enrichment", "updated_at",
                                       "TIMESTAMP NOT NULL DEFAULT NOW()")
            if "retry_count" not in de_cols:
                _add_column_if_missing(conn, "rag_document_enrichment", "retry_count",
                                       "INTEGER NOT NULL DEFAULT 0")

        # Phase-2 ingestion: per-file embedding columns. Older rag_uploaded_files
        # tables (created before this feature shipped) miss these.
        if "rag_uploaded_files" in inspector.get_table_names():
            uf_cols = [c["name"] for c in inspector.get_columns("rag_uploaded_files")]
            if "embedded_count" not in uf_cols:
                _add_column_if_missing(conn, "rag_uploaded_files", "embedded_count",
                                       "INTEGER NOT NULL DEFAULT 0")
            if "vectors_ready" not in uf_cols:
                _add_column_if_missing(conn, "rag_uploaded_files", "vectors_ready",
                                       "BOOLEAN NOT NULL DEFAULT FALSE")

        conn.commit()

    logger.info("[db] Schema up-to-date")


@contextmanager
def get_db():
    """Context-manager DB session. Usage: ``with get_db() as db: ...``"""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
