"""SQLAlchemy ORM models for RAG sessions and messages.

Tables:
  rag_sessions       — one row per conversation thread
  rag_messages       — individual chat messages (user + assistant)
  rag_insights_cache — cached LLM-generated intelligence reports
"""
import uuid
from datetime import datetime, timezone

from contextlib import contextmanager

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, JSON,
    ForeignKey, create_engine, Index, text, event, exc as sa_exc
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from src.config import Config
from framework.commons.logger import logger

Base = declarative_base()

# ── Models ─────────────────────────────────────────────────────────────────────

class Session(Base):
    """A conversation session — groups all messages in one chat thread."""
    __tablename__ = "rag_sessions"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title       = Column(String(255), nullable=True)           # user-set or auto-generated
    datasource  = Column(String(100), nullable=False, default="default")
    created_at  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime, nullable=False,
                         default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    messages = relationship(
        "Message",
        back_populates="session",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "datasource": self.datasource,
            "message_count": len(self.messages) if self.messages else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Message(Base):
    """A single chat turn — either 'user' or 'assistant'."""
    __tablename__ = "rag_messages"

    id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("rag_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    role       = Column(String(20), nullable=False)   # "user" | "assistant"
    content    = Column(Text, nullable=False)
    # retrieved chunk IDs + scores used to generate this assistant message
    sources    = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", back_populates="messages")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "sources": self.sources,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class InsightsCache(Base):
    """Granular cached insights and background tasks.

    Each insight type (summary, ner, stats, etc.) is its own row, allowing
    partial updates and independent background generation.
    """
    __tablename__ = "rag_insights_cache"

    datasource   = Column(String(100), primary_key=True, default="default")
    insight_type = Column(String(50),  primary_key=True)  # "summary" | "ner" | "graph" | "stats"

    status       = Column(String(20),  nullable=False, default="pending", index=True)
    payload      = Column(JSON,        nullable=True)
    error        = Column(Text,        nullable=True)

    # Lifecycle timestamps
    generated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at   = Column(DateTime, nullable=True)   # when worker picked it up
    updated_at   = Column(DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    retry_count  = Column(Integer,  nullable=False, default=0)
    sample_hash  = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_insights_datasource_type", "datasource", "insight_type"),
    )

    def to_dict(self):
        return {
            "datasource":   self.datasource,
            "insight_type": self.insight_type,
            "status":       self.status,
            "payload":      self.payload,
            "error":        self.error,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "started_at":   self.started_at.isoformat()   if self.started_at   else None,
            "updated_at":   self.updated_at.isoformat()   if self.updated_at   else None,
            "retry_count":  self.retry_count,
            "sample_hash":  self.sample_hash,
        }


class DocumentStatus(Base):
    """Analyst-assigned review status for a document.

    Statuses: 'in_progress' | 'done'
    A missing row means no status has been set.
    """
    __tablename__ = "rag_document_status"

    doc_id     = Column(String(255), primary_key=True)
    datasource = Column(String(100), primary_key=True)
    status     = Column(String(20),  nullable=False)   # 'in_progress' | 'done'
    updated_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "doc_id":     self.doc_id,
            "datasource": self.datasource,
            "status":     self.status,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentLabel(Base):
    """Analyst-assigned labels/tags for a document.

    Labels are arbitrary strings (e.g. case names, campaign IDs) that help
    analysts find related documents across different search sessions.
    A missing row means no labels have been assigned.
    """
    __tablename__ = "rag_document_labels"

    doc_id     = Column(String(255), primary_key=True)
    datasource = Column(String(100), primary_key=True)
    labels     = Column(JSON, nullable=False, default=list)  # ["label1", "label2"]
    updated_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "doc_id":     self.doc_id,
            "datasource": self.datasource,
            "labels":     self.labels or [],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentEnrichment(Base):
    """Cache for AI enrichment (sentiment, NER, classification, summary) on a single document."""
    __tablename__ = "rag_document_enrichment"

    doc_id     = Column(String(255), primary_key=True)
    datasource = Column(String(100), primary_key=True)

    status  = Column(String(20), nullable=False, default="pending", index=True)
    payload = Column(JSON,       nullable=True)
    error   = Column(Text,       nullable=True)

    # Lifecycle timestamps
    generated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at   = Column(DateTime, nullable=True)
    updated_at   = Column(DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    retry_count  = Column(Integer, nullable=False, default=0)

    def to_dict(self):
        return {
            "doc_id":       self.doc_id,
            "datasource":   self.datasource,
            "status":       self.status,
            "payload":      self.payload,
            "error":        self.error,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "started_at":   self.started_at.isoformat()   if self.started_at   else None,
            "updated_at":   self.updated_at.isoformat()   if self.updated_at   else None,
            "retry_count":  self.retry_count,
        }

# ── Engine / session factory ───────────────────────────────────────────────────

_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        kwargs = {"pool_pre_ping": True}
        if Config.DATABASE_URL.startswith("postgresql"):
            kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_recycle": 300})
        _engine = create_engine(Config.DATABASE_URL, **kwargs)

        @event.listens_for(_engine, "checkout")
        def _validate_connection(dbapi_conn, conn_record, conn_proxy):
            """Pessimistic checkout validation — discard connections in bad state.

            pool_pre_ping catches dead connections (network-level), but not ones
            stuck in a broken transaction (PGRES_TUPLES_OK error). This ping runs
            on every checkout and raises DisconnectionError to force pool recycling.
            """
            try:
                dbapi_conn.cursor().execute("SELECT 1")
            except Exception:
                raise sa_exc.DisconnectionError()

    return _engine


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionFactory


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    """ALTER TABLE helper — silently skips if column already exists."""
    conn.execute(text(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
    ))


def init_db():
    """Create all tables and apply incremental schema migrations.

    Uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so it is safe to run on
    every startup — no-ops when the schema is already current.
    """
    engine = get_engine()
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # ── Legacy migration: drop old single-column insights table ──────────────
    if "rag_insights_cache" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("rag_insights_cache")]
        if "insight_type" not in cols:
            logger.warning("[db] Old rag_insights_cache schema — dropping for rebuild")
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS rag_insights_cache CASCADE"))
                conn.commit()

    # ── Create any missing tables ─────────────────────────────────────────────
    Base.metadata.create_all(bind=engine)

    # ── Incremental column additions ──────────────────────────────────────────
    with engine.connect() as conn:
        # InsightsCache — new lifecycle columns
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

        # DocumentEnrichment — new lifecycle columns
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

        conn.commit()

    logger.info("[db] Schema up-to-date")


@contextmanager
def get_db():
    """Context-manager-friendly DB session. Usage: with get_db() as db: ..."""
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
