"""Public service layer for ingestion.

The API and frontend never reach into ``handlers/`` or ``pipeline.py``
directly — they go through this module. Each function is small and
transactional; the heavy lifting happens in tasks/pipeline.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional

from sqlalchemy.exc import IntegrityError
from framework.commons.logger import logger

from src.core.db import get_db
from src.ingestion import profiles
from src.ingestion.models import UploadedFile
from src.ingestion.storage import (
    FileTooLargeError, StorageError, StoredFile, get_storage,
)


# ── Custom errors raised to API layer ─────────────────────────────────────────

class DuplicateUploadError(Exception):
    """Raised when an identical file (same sha256) already exists in the
    investigation. Carries the existing file's id so the API can return it."""
    def __init__(self, existing_id: str):
        super().__init__(f"file already uploaded as {existing_id}")
        self.existing_id = existing_id


# ── Create ────────────────────────────────────────────────────────────────────

def create_upload(investigation_id: str, filename: str,
                  stream: BinaryIO,
                  mime_type: Optional[str] = None) -> dict:
    """Stream the upload to disk, persist a row, and queue ``ingest_file``.

    Idempotency: the ``(investigation_id, sha256)`` UNIQUE constraint catches
    re-uploads of the same bytes — we delete the just-written file and
    raise ``DuplicateUploadError`` carrying the existing file id.
    """
    storage = get_storage()
    file_id = str(uuid.uuid4())

    try:
        stored: StoredFile = storage.write(investigation_id, file_id, filename, stream)
    except FileTooLargeError as e:
        raise
    except StorageError as e:
        logger.error(f"[ingest] storage write failed: {e}")
        raise

    storage.write_meta(investigation_id, file_id, {
        "filename":    filename,
        "size":        stored.size,
        "sha256":      stored.sha256,
        "mime":        mime_type,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    })

    # Persist the row. Race-conditions on the dedup constraint are handled
    # by trapping IntegrityError and tearing down the just-written file.
    try:
        with get_db() as db:
            row = UploadedFile(
                id=file_id,
                investigation_id=investigation_id,
                filename=filename,
                storage_uri=stored.uri,
                size_bytes=stored.size,
                sha256=stored.sha256,
                mime_type=mime_type,
                status="pending",
            )
            db.add(row)
            db.flush()
            result = row.to_dict()
    except IntegrityError:
        storage.delete(investigation_id, file_id)
        existing = _find_by_sha256(investigation_id, stored.sha256)
        existing_id = existing["id"] if existing else "unknown"
        raise DuplicateUploadError(existing_id)

    # Queue stage-1 work. Late-import so this module remains importable
    # in tests where Kafka isn't running.
    from src.tasking.producer import publish_task
    publish_task({
        "task_type":        "ingest_file",
        "file_id":          file_id,
        "investigation_id": investigation_id,
        "datasource":       investigation_id,  # fast_tasks routing key
    })

    logger.info(f"[ingest] queued ingest_file for {file_id} (size={stored.size})")
    return result


def _find_by_sha256(investigation_id: str, sha256: str) -> Optional[dict]:
    with get_db() as db:
        row = (
            db.query(UploadedFile)
            .filter_by(investigation_id=investigation_id, sha256=sha256)
            .first()
        )
        return row.to_dict() if row else None


# ── Read ──────────────────────────────────────────────────────────────────────

def get_upload(file_id: str) -> Optional[dict]:
    with get_db() as db:
        row = db.query(UploadedFile).filter_by(id=file_id).first()
        return row.to_dict() if row else None


def list_uploads(investigation_id: str) -> list[dict]:
    with get_db() as db:
        rows = (
            db.query(UploadedFile)
            .filter_by(investigation_id=investigation_id)
            .order_by(UploadedFile.created_at.desc())
            .all()
        )
        return [r.to_dict() for r in rows]


# ── Confirm mapping ───────────────────────────────────────────────────────────

def confirm_mapping(file_id: str, mapping: dict, options: Optional[dict] = None,
                    save_as_profile: bool = False,
                    profile_name: Optional[str] = None) -> Optional[dict]:
    """User-confirmed (or edited) mapping → transition to ``indexing``.

    If ``save_as_profile=True`` we upsert a ``ParserProfile`` for the
    handler/fingerprint pair so the next structurally-identical upload
    skips review entirely. The fingerprint comes from the
    ``proposed_mapping`` blob written by ``run_parse``.
    """
    with get_db() as db:
        row = db.query(UploadedFile).filter_by(id=file_id).first()
        if row is None:
            return None
        if row.status != "mapping_review":
            logger.warning(
                f"[ingest] confirm_mapping: file {file_id} in status {row.status!r} "
                f"(expected mapping_review) — proceeding anyway"
            )
        merged_options = {**(row.options or {}), **(options or {})}
        proposed = row.proposed_mapping or {}

        # Persist + transition
        row.final_mapping = mapping
        row.options = merged_options
        row.status = "indexing"
        row.indexed_count = 0
        row.error = None
        row.updated_at = datetime.now(timezone.utc)
        # snapshot for the profile upsert below
        handler_name = row.handler_name
        fingerprint = (proposed.get("fingerprint") if isinstance(proposed, dict) else None)
        sample = proposed.get("samples") if isinstance(proposed, dict) else None
        db.flush()
        result = row.to_dict()

    if save_as_profile and handler_name and fingerprint:
        try:
            saved = profiles.upsert(
                handler_name=handler_name,
                fingerprint=fingerprint,
                mapping=mapping,
                options=merged_options,
                sample=sample,
                name=profile_name,
            )
            # Link the file to its profile for traceability. Re-open the
            # session to keep the profile upsert and the link in distinct
            # transactions (profile upsert is interesting on its own and
            # shouldn't roll back if the link fails).
            with get_db() as db:
                row = db.query(UploadedFile).filter_by(id=file_id).first()
                if row is not None:
                    row.profile_id = saved["id"]
            # The dict captured above is stale w.r.t. profile_id — patch it
            # so callers (incl. the API) see the link they just requested.
            result["profile_id"] = saved["id"]
        except Exception as e:
            logger.warning(f"[ingest] profile save failed (non-fatal): {e}")

    # Hand off to stage-2.
    from src.tasking.producer import publish_task
    publish_task({
        "task_type":        "ingest_continue",
        "file_id":          file_id,
        "investigation_id": result["investigation_id"],
        "datasource":       result["investigation_id"],
    })
    return result


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_upload(file_id: str, purge_es: bool = False) -> bool:
    """Remove the upload row + the original file. Optionally also delete
    the ES docs that came from this upload.

    Note: ``purge_es`` does a delete-by-query on ``source_file = file_id``;
    this is a heavier operation and may take seconds-to-minutes on large
    indices. Acceptable for an admin action.
    """
    storage = get_storage()
    investigation_id: Optional[str] = None
    with get_db() as db:
        row = db.query(UploadedFile).filter_by(id=file_id).first()
        if row is None:
            return False
        investigation_id = row.investigation_id
        db.delete(row)

    try:
        storage.delete(investigation_id, file_id)
    except Exception as e:
        logger.warning(f"[ingest] delete: storage purge failed: {e}")

    if purge_es and investigation_id:
        try:
            from src.investigations.service import get_investigation
            from src.retrieval.es_client import ESClient
            inv = get_investigation(investigation_id)
            if inv:
                es = ESClient()
                es._client.delete_by_query(
                    index=inv["index_name"],
                    body={"query": {"term": {"source_file": file_id}}},
                    conflicts="proceed",
                    refresh=True,
                )
        except Exception as e:
            logger.warning(f"[ingest] delete: ES purge failed: {e}")

    return True


def storage_path_for_download(file_id: str) -> Optional[Path]:
    """Resolve the on-disk path for streaming the original back to the
    user (download endpoint). Returns None if the row or file is missing.
    """
    rec = get_upload(file_id)
    if rec is None:
        return None
    storage = get_storage()
    try:
        return storage.path_for(rec["investigation_id"], file_id)
    except Exception:
        return None
