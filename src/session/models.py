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
    ForeignKey, create_engine, Index,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from src.config import Config

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
    """Cached AI-generated intelligence report for a datasource.

    One row per datasource. Overwritten on each refresh.
    TTL logic is handled in InsightsEngine (compared to generated_at).
    """
    __tablename__ = "rag_insights_cache"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    datasource   = Column(String(100), nullable=False, unique=True, default="default")
    payload      = Column(JSON, nullable=False)          # full insights dict from LLM
    generated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_insights_datasource_ts", "datasource", "generated_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "datasource": self.datasource,
            "payload": self.payload,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


# ── Engine / session factory ───────────────────────────────────────────────────

_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        kwargs = {"pool_pre_ping": True}
        if Config.DATABASE_URL.startswith("postgresql"):
            kwargs.update({"pool_size": 10, "max_overflow": 20})
        _engine = create_engine(Config.DATABASE_URL, **kwargs)
    return _engine


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionFactory


def init_db():
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=get_engine())


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
