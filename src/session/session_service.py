"""CRUD operations for RAG sessions, messages, saved searches, and investigations.

All functions accept/return plain dicts (no ORM objects leak to callers).
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import joinedload
from framework.commons.logger import logger

from src.session.models import (
    Session, Message, SavedSearch, Investigation, InvestigationSearch, get_db,
)


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


# ── Saved Searches ─────────────────────────────────────────────────────────────

def list_saved_searches() -> list[dict]:
    """Return all saved searches ordered by most recently updated."""
    with get_db() as db:
        rows = db.query(SavedSearch).order_by(SavedSearch.updated_at.desc()).all()
        return [r.to_dict() for r in rows]


def create_saved_search(
    name: str,
    description: Optional[str] = None,
    query: str = "",
    filters: Optional[dict] = None,
) -> dict:
    """Create a new saved search and return its dict."""
    with get_db() as db:
        row = SavedSearch(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            query=query,
            filters=filters or {},
        )
        db.add(row)
        db.flush()
        result = row.to_dict()
    logger.debug(f"[search] Created saved search {result['id']} name={name!r}")
    return result


def update_saved_search(
    search_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    query: Optional[str] = None,
    filters: Optional[dict] = None,
) -> Optional[dict]:
    """Update a saved search. Returns updated dict or None if not found."""
    with get_db() as db:
        row = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        if row is None:
            return None
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if query is not None:
            row.query = query
        if filters is not None:
            row.filters = filters
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        return row.to_dict()


def delete_saved_search(search_id: str) -> bool:
    """Delete a saved search. Returns True if found and deleted."""
    with get_db() as db:
        row = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        if row is None:
            return False
        db.delete(row)
    logger.debug(f"[search] Deleted saved search {search_id}")
    return True


def get_saved_search(search_id: str) -> Optional[dict]:
    """Return a single saved search or None."""
    with get_db() as db:
        row = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        return row.to_dict() if row else None


# ── Investigations ─────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convert investigation name to a valid ES index name segment."""
    slug = re.sub(r'[^\w]+', '_', name.lower()).strip('_')
    # ES index names can't start with _ or -
    if slug and slug[0].isdigit():
        slug = 'inv_' + slug
    return slug[:40] or 'investigation'


def list_investigations() -> list[dict]:
    """Return all investigations ordered by most recently created."""
    with get_db() as db:
        rows = (
            db.query(Investigation)
            .options(joinedload(Investigation.search_links))
            .order_by(Investigation.created_at.desc())
            .all()
        )
        return [
            r.to_dict(search_ids=[lnk.search_id for lnk in r.search_links])
            for r in rows
        ]


def create_investigation(
    name: str,
    description: Optional[str] = None,
    search_ids: Optional[list[str]] = None,
) -> dict:
    """Create investigation row + search links and return dict.

    Does NOT trigger the background index-creation task — the caller is
    responsible for publishing that after the DB commit succeeds.
    """
    inv_id = str(uuid.uuid4())
    slug = _slugify(name)
    index_name = f"inv_{slug}_{inv_id[:8]}"

    with get_db() as db:
        inv = Investigation(
            id=inv_id,
            name=name,
            description=description,
            index_name=index_name,
            status="creating",
        )
        db.add(inv)
        db.flush()  # get the PK assigned

        for sid in (search_ids or []):
            db.add(InvestigationSearch(investigation_id=inv_id, search_id=sid))
        db.flush()

        result = inv.to_dict(search_ids=list(search_ids or []))

    logger.info(f"[investigation] Created {inv_id} index={index_name}")
    return result


def get_investigation(investigation_id: str) -> Optional[dict]:
    """Return investigation dict with search_ids or None if not found."""
    with get_db() as db:
        row = (
            db.query(Investigation)
            .options(joinedload(Investigation.search_links))
            .filter(Investigation.id == investigation_id)
            .first()
        )
        if row is None:
            return None
        return row.to_dict(search_ids=[lnk.search_id for lnk in row.search_links])


def update_investigation_status(
    investigation_id: str,
    status: str,
    error_msg: Optional[str] = None,
    doc_count: Optional[int] = None,
) -> None:
    """Update investigation status (called from background task handler)."""
    with get_db() as db:
        row = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if row is None:
            logger.warning(f"[investigation] update_status: id={investigation_id} not found")
            return
        row.status = status
        if error_msg is not None:
            row.error_msg = error_msg
        if doc_count is not None:
            row.doc_count = doc_count
        row.updated_at = datetime.now(timezone.utc)
        db.commit()


def delete_investigation(investigation_id: str) -> Optional[str]:
    """Delete investigation DB row. Returns index_name so caller can delete ES index."""
    with get_db() as db:
        row = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if row is None:
            return None
        index_name = row.index_name
        db.delete(row)
    logger.info(f"[investigation] Deleted {investigation_id} index={index_name}")
    return index_name
