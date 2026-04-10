"""CRUD operations for RAG sessions and messages.

All functions accept/return plain dicts (no ORM objects leak to callers).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from framework.commons.logger import logger

from src.session.models import Session, Message, get_db


def create_session(title: Optional[str] = None, datasource: str = "default") -> dict:
    """Create a new chat session and return its dict representation."""
    with get_db() as db:
        session = Session(
            id=str(uuid.uuid4()),
            title=title,
            datasource=datasource,
        )
        db.add(session)
        db.flush()
        result = session.to_dict()
    logger.debug(f"[session] Created session {result['id']}")
    return result


def get_session(session_id: str) -> Optional[dict]:
    """Return session dict or None if not found."""
    with get_db() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if session is None:
            return None
        return session.to_dict()


def list_sessions(datasource: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List sessions, most recent first. Optionally filter by datasource."""
    with get_db() as db:
        q = db.query(Session)
        if datasource:
            q = q.filter(Session.datasource == datasource)
        sessions = q.order_by(Session.updated_at.desc()).limit(limit).all()
        return [s.to_dict() for s in sessions]


def update_session_title(session_id: str, title: str) -> Optional[dict]:
    """Rename a session. Returns updated dict or None if not found."""
    with get_db() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if session is None:
            return None
        session.title = title
        session.updated_at = datetime.now(timezone.utc)
        db.flush()
        return session.to_dict()


def delete_session(session_id: str) -> bool:
    """Delete session and all its messages (cascade). Returns True if found."""
    with get_db() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if session is None:
            return False
        db.delete(session)
    logger.debug(f"[session] Deleted session {session_id}")
    return True


def append_message(
    session_id: str,
    role: str,
    content: str,
    sources: Optional[list] = None,
) -> dict:
    """Append a message to a session. Also bumps session.updated_at."""
    with get_db() as db:
        # Touch the session timestamp so ordering works correctly
        session = db.query(Session).filter(Session.id == session_id).first()
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        session.updated_at = datetime.now(timezone.utc)

        # Auto-title: first user message becomes the session title
        if role == "user" and session.title is None:
            session.title = content[:80] + ("…" if len(content) > 80 else "")

        msg = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            sources=sources,
        )
        db.add(msg)
        db.flush()
        result = msg.to_dict()

    return result


def get_messages(session_id: str) -> list[dict]:
    """Return all messages for a session in chronological order."""
    with get_db() as db:
        messages = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return [m.to_dict() for m in messages]


def get_recent_messages(session_id: str, turns: int = 10) -> list[dict]:
    """Return the last `turns` message pairs (user + assistant) for the session.

    Used to build conversation history for the LLM context window.
    """
    with get_db() as db:
        messages = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(turns * 2)   # each turn = user + assistant
            .all()
        )
        # Reverse so they are in chronological order
        return [m.to_dict() for m in reversed(messages)]
