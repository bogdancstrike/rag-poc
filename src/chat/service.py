"""CRUD operations for chat sessions and messages."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import joinedload
from framework.commons.logger import logger

from src.core.db import get_db
from src.chat.models import Session, Message


def create_session(title: Optional[str] = None, datasource: str = "default") -> dict:
    with get_db() as db:
        session = Session(id=str(uuid.uuid4()), title=title, datasource=datasource)
        db.add(session)
        db.flush()
        result = session.to_dict()
    logger.debug(f"[session] Created session {result['id']}")
    return result


def get_session(session_id: str) -> Optional[dict]:
    with get_db() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        return session.to_dict() if session else None


def list_sessions(datasource: Optional[str] = None, limit: int = 50) -> list[dict]:
    with get_db() as db:
        q = db.query(Session)
        if datasource:
            q = q.filter(Session.datasource == datasource)
        return [s.to_dict() for s in q.order_by(Session.updated_at.desc()).limit(limit).all()]


def update_session_title(session_id: str, title: str) -> Optional[dict]:
    with get_db() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if session is None:
            return None
        session.title = title
        session.updated_at = datetime.now(timezone.utc)
        db.flush()
        return session.to_dict()


def delete_session(session_id: str) -> bool:
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
    with get_db() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        session.updated_at = datetime.now(timezone.utc)
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
    with get_db() as db:
        messages = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return [m.to_dict() for m in messages]


def get_recent_messages(session_id: str, turns: int = 10) -> list[dict]:
    with get_db() as db:
        messages = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(turns * 2)
            .all()
        )
        return [m.to_dict() for m in reversed(messages)]
