"""Parser-profile lookup + upsert.

A *profile* caches the mapping/options decided for a particular structural
fingerprint (e.g. set of CSV headers). When the same shape arrives again we
skip the LLM call and the user-confirmation step entirely.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from framework.commons.logger import logger

from src.core.db import get_db
from src.ingestion.models import ParserProfile


def find_by_fingerprint(handler_name: str, fingerprint: str) -> Optional[dict]:
    """Look up a profile by (handler, fingerprint). Returns the dict form
    or None. *Does not* increment usage_count — call ``mark_used`` on the
    profile id if the caller actually applies it."""
    if not fingerprint:
        return None
    with get_db() as db:
        row = (
            db.query(ParserProfile)
            .filter_by(handler_name=handler_name, fingerprint=fingerprint)
            .first()
        )
        return row.to_dict() if row else None


def mark_used(profile_id: str) -> None:
    """Increment ``usage_count`` and refresh ``last_used_at``. Best-effort —
    a missing profile (deleted between lookup and mark) is logged, not raised.
    """
    with get_db() as db:
        row = db.query(ParserProfile).filter_by(id=profile_id).first()
        if row is None:
            logger.warning(f"[profiles] mark_used: profile {profile_id} missing")
            return
        row.usage_count = (row.usage_count or 0) + 1
        row.last_used_at = datetime.now(timezone.utc)


def upsert(handler_name: str, fingerprint: str, mapping: dict, options: dict,
           sample: Optional[list] = None, name: Optional[str] = None) -> dict:
    """Insert a new profile or update an existing one for the same
    (handler, fingerprint). The mapping/options of the most recent confirm
    win — earlier confirmations are overwritten on purpose, since they're
    almost certainly being corrected.
    """
    with get_db() as db:
        row = (
            db.query(ParserProfile)
            .filter_by(handler_name=handler_name, fingerprint=fingerprint)
            .first()
        )
        if row is None:
            row = ParserProfile(
                id=str(uuid.uuid4()),
                handler_name=handler_name,
                fingerprint=fingerprint,
                name=name,
                mapping=mapping,
                options=options or {},
                sample=sample,
                usage_count=0,
            )
            db.add(row)
        else:
            row.mapping = mapping
            row.options = options or {}
            if sample is not None:
                row.sample = sample
            if name is not None:
                row.name = name
        db.flush()
        return row.to_dict()


def list_profiles(handler_name: Optional[str] = None) -> list[dict]:
    with get_db() as db:
        q = db.query(ParserProfile)
        if handler_name:
            q = q.filter_by(handler_name=handler_name)
        return [r.to_dict() for r in q.order_by(ParserProfile.created_at.desc()).all()]


def delete_profile(profile_id: str) -> bool:
    with get_db() as db:
        row = db.query(ParserProfile).filter_by(id=profile_id).first()
        if row is None:
            return False
        db.delete(row)
    return True
