"""CRUD operations for saved searches and investigations."""
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import joinedload
from framework.commons.logger import logger

from src.core.db import get_db
from src.investigations.models import (
    SavedSearch, Investigation, InvestigationSearch,
    DocumentStatus, DocumentLabel,
)


# ── Saved Searches ─────────────────────────────────────────────────────────────

def list_saved_searches() -> list[dict]:
    with get_db() as db:
        rows = db.query(SavedSearch).order_by(SavedSearch.updated_at.desc()).all()
        return [r.to_dict() for r in rows]


def create_saved_search(
    name: str,
    description: Optional[str] = None,
    query: str = "",
    filters: Optional[dict] = None,
) -> dict:
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
    with get_db() as db:
        row = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        if row is None:
            return False
        db.delete(row)
    logger.debug(f"[search] Deleted saved search {search_id}")
    return True


def get_saved_search(search_id: str) -> Optional[dict]:
    with get_db() as db:
        row = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        return row.to_dict() if row else None


# ── Investigations ─────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    slug = re.sub(r'[^\w]+', '_', name.lower()).strip('_')
    if slug and slug[0].isdigit():
        slug = 'inv_' + slug
    return slug[:40] or 'investigation'


def list_investigations() -> list[dict]:
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
        db.flush()
        for sid in (search_ids or []):
            db.add(InvestigationSearch(investigation_id=inv_id, search_id=sid))
        db.flush()
        result = inv.to_dict(search_ids=list(search_ids or []))

    logger.info(f"[investigation] Created {inv_id} index={index_name}")
    return result


def get_investigation(investigation_id: str) -> Optional[dict]:
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
    from src.insights.models import InsightsCache
    from src.enrichment.models import DocumentEnrichment
    with get_db() as db:
        row = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if row is None:
            return None
        index_name = row.index_name
        enrichment_deleted = db.query(DocumentEnrichment).filter_by(
            datasource=index_name
        ).delete(synchronize_session=False)
        insight_deleted = db.query(InsightsCache).filter_by(
            datasource=index_name
        ).delete(synchronize_session=False)
        db.delete(row)

    logger.info(
        f"[investigation] Deleted {investigation_id} index={index_name} "
        f"enrichment_tasks={enrichment_deleted} insight_tasks={insight_deleted}"
    )
    return index_name
