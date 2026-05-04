"""Ingestion pipeline orchestrator — the streaming state machine.

Drives an ``UploadedFile`` row through:

    pending → parsing → mapping_review → indexing → complete | error

The pipeline is split into ``run_parse`` (sniff + fingerprint + propose) and
``run_index`` (extract + bulk-index). Both functions are called from task
handlers (``ingestion.tasks``) and are safe to retry — the file is on disk,
ES upserts on stable ``_id``, and the DB row's status drives any cleanup.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from elasticsearch import helpers as es_helpers
from framework.commons.logger import logger

from src.config import Config
from src.core.db import get_db
from src.ingestion import handlers as handler_pkg     # noqa: F401 — ensures registry init
from src.ingestion import llm_mapping, normalizer, profiles
from src.ingestion.handlers import get_for
from src.ingestion.handlers.base import FileHandler, MappingProposal, RawRecord
from src.ingestion.models import UploadedFile
from src.ingestion.storage import get_storage


# ── Status helpers ────────────────────────────────────────────────────────────

def _set_status(file_id: str, status: str, **fields) -> Optional[UploadedFile]:
    """Atomic status update. Pass keyword fields to update arbitrary columns
    in the same transaction (error, indexed_count, etc.)."""
    with get_db() as db:
        row = db.query(UploadedFile).filter_by(id=file_id).first()
        if row is None:
            logger.warning(f"[ingest] _set_status: file {file_id} missing")
            return None
        row.status = status
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        return row


def _row_dict(file_id: str) -> Optional[dict]:
    with get_db() as db:
        row = db.query(UploadedFile).filter_by(id=file_id).first()
        return row.to_dict() if row else None


# ── Stage 1: parse + propose ──────────────────────────────────────────────────

def run_parse(file_id: str) -> None:
    """Pick a handler, compute fingerprint, propose mapping.

    Three terminal outcomes for this stage:

    a) Profile cache hit       → ``final_mapping`` populated; transitions
                                  straight to ``indexing`` and queues
                                  ``ingest_continue``.
    b) Mapping inferred fresh  → ``proposed_mapping`` populated; transitions
                                  to ``mapping_review``. The user confirms
                                  via the API to advance.
    c) Failure                 → ``error``; ``error`` column populated.
    """
    storage = get_storage()
    record = _row_dict(file_id)
    if record is None:
        logger.error(f"[ingest] run_parse: file {file_id} missing")
        return
    investigation_id = record["investigation_id"]
    filename = record["filename"]
    options = record.get("options") or {}

    try:
        path: Path = storage.path_for(investigation_id, file_id)
    except Exception as e:
        _set_status(file_id, "error", error=f"file unavailable: {e}")
        return

    _set_status(file_id, "parsing")

    handler = get_for(path, record.get("mime_type"))
    if handler is None:
        _set_status(file_id, "error", error="no handler matched this file")
        return

    # Compute fingerprint and check the profile cache.
    try:
        fp = handler.fingerprint(path, options)
    except Exception as e:
        logger.warning(f"[ingest] fingerprint failed for {file_id}: {e}")
        fp = None

    cached = profiles.find_by_fingerprint(handler.name, fp) if fp else None
    if cached:
        # Profile cache hit — skip proposal entirely.
        merged_options = {**(cached.get("options") or {}), **options}
        _set_status(
            file_id, "indexing",
            handler_name=handler.name,
            profile_id=cached["id"],
            final_mapping=cached["mapping"],
            options=merged_options,
        )
        profiles.mark_used(cached["id"])
        logger.info(
            f"[ingest] {file_id}: profile cache hit ({handler.name}/{fp[:12]}…) "
            f"→ skipping mapping_review"
        )
        # Fan straight into the indexing stage on the same worker thread —
        # avoids an extra Kafka round-trip when we already have the file.
        run_index(file_id)
        return

    # Cache miss — propose a mapping (heuristic + optional LLM refinement).
    try:
        proposal: MappingProposal = handler.propose_mapping(path, options)
    except Exception as e:
        logger.error(f"[ingest] propose_mapping failed for {file_id}: {e}", exc_info=True)
        _set_status(file_id, "error", error=f"propose_mapping failed: {e}")
        return

    refined = llm_mapping.refine_mapping(
        handler.name, proposal.columns, proposal.samples,
        proposal.suggested_mapping or {},
    )

    proposed = {
        "handler":    handler.name,
        "fingerprint": fp,
        "columns":    proposal.columns,
        "samples":    proposal.samples,
        "mapping":    refined["mapping"],
        "options":    proposal.options,
        "confidence": refined["confidence"],
        "rationale":  refined["rationale"],
        "source":     refined["source"],
    }

    _set_status(
        file_id, "mapping_review",
        handler_name=handler.name,
        proposed_mapping=proposed,
        options=proposal.options,
    )
    logger.info(
        f"[ingest] {file_id}: proposed mapping awaiting confirmation "
        f"({handler.name}, source={refined['source']})"
    )


# ── Stage 2: index ────────────────────────────────────────────────────────────

def run_index(file_id: str) -> None:
    """Stream ``handler.extract`` → batched ES bulk-index. Idempotent —
    re-running upserts onto the same ``_id`` so duplicate work after a
    restart is safe."""
    from src.investigations.service import get_investigation
    from src.retrieval.es_client import ESClient

    storage = get_storage()
    record = _row_dict(file_id)
    if record is None:
        logger.error(f"[ingest] run_index: file {file_id} missing")
        return

    investigation_id = record["investigation_id"]
    inv = get_investigation(investigation_id)
    if inv is None:
        _set_status(file_id, "error", error=f"investigation {investigation_id} missing")
        return
    index_name = inv["index_name"]

    handler = get_for(storage.path_for(investigation_id, file_id), record.get("mime_type"))
    if handler is None or handler.name != record.get("handler_name"):
        _set_status(file_id, "error", error="handler resolution drift between stages")
        return

    mapping = record.get("final_mapping") or {}
    options = record.get("options") or {}
    if not mapping:
        # Confirmation never happened or was reset — surface clearly.
        _set_status(file_id, "error", error="run_index called without final_mapping")
        return

    # Best-effort upfront record count so the UI's progress bar shows a
    # meaningful percentage from the first batch. ``estimate_records``
    # never blows up indexing — None just means we keep showing only
    # the "indexed" running total without a denominator.
    try:
        est = handler.estimate_records(
            storage.path_for(investigation_id, file_id), options,
        )
    except Exception as e:
        logger.warning(f"[ingest] estimate_records failed: {e}")
        est = None

    _set_status(file_id, "indexing", indexed_count=0,
                record_count=est, error=None)

    es = ESClient()
    # Investigation index already exists (created by handle_create_investigation).
    # Use ensure_index as a defensive idempotent call in case uploads run
    # against an old investigation whose index was rebuilt.
    try:
        es.create_index(index_name)
    except Exception:
        # create_index treats existing-index as success; only re-raise on
        # deeper failures, which we surface below via bulk-index errors.
        pass

    path = storage.path_for(investigation_id, file_id)
    batch: list[dict] = []
    indexed = 0
    seen = 0

    def _flush():
        nonlocal batch, indexed
        if not batch:
            return
        try:
            success, errors = es_helpers.bulk(
                es._client, batch, raise_on_error=False, request_timeout=60,
            )
            indexed += success
            if errors:
                # Only log; per-doc failures shouldn't kill the whole upload.
                logger.warning(f"[ingest] {file_id}: {len(errors)} per-doc bulk errors "
                               f"(first: {str(errors[0])[:200]})")
        finally:
            batch = []

    try:
        for rec in handler.extract(path, mapping, options):
            seen += 1
            doc = normalizer.normalize(rec, file_id, record["filename"])
            batch.append({
                "_op_type": "index",
                "_index":   index_name,
                "_id":      normalizer.stable_doc_id(file_id, rec.record_index),
                "_source":  doc,
            })
            if len(batch) >= Config.INGEST_BATCH_SIZE:
                _flush()
                _set_status(file_id, "indexing", indexed_count=indexed, record_count=seen)
        _flush()

        try:
            es._client.indices.refresh(index=index_name)
        except Exception as e:
            logger.warning(f"[ingest] refresh after index failed: {e}")

        _set_status(file_id, "complete", indexed_count=indexed, record_count=seen)
        logger.info(
            f"[ingest] {file_id}: complete records={seen} indexed={indexed} "
            f"index={index_name}",
            "magenta",
        )

        # Kick off per-file embedding so this upload becomes hybrid-
        # searchable on its own, without waiting for an all-or-nothing
        # re-embed of the whole investigation. ``embed_file`` filters by
        # ``source_file = file_id`` and only touches our records.
        if indexed > 0:
            from src.tasking.producer import publish_task
            publish_task({
                "task_type":        "embed_file",
                "file_id":          file_id,
                "investigation_id": investigation_id,
                "datasource":       index_name,
            })

    except Exception as e:
        logger.error(f"[ingest] run_index failed for {file_id}: {e}", exc_info=True)
        _set_status(file_id, "error", error=str(e), indexed_count=indexed, record_count=seen)
        raise


# ── Stage 3: per-file embedding ───────────────────────────────────────────────

def run_embed(file_id: str) -> None:
    """Embed only the records this file produced (filtered by ``source_file``).

    Designed for incremental upgrade BM25 → hybrid: each upload becomes
    fully searchable independently of the rest of the investigation. The
    ``UploadedFile.embedded_count`` and ``vectors_ready`` flags advance as
    we go so the UI can show ``"BM25 ready · embedding 320 / 1000"``
    while the work is in progress.
    """
    from src.investigations.service import get_investigation
    from src.retrieval.es_client import ESClient
    from src.retrieval.embedding_client import get_embedding_client

    record = _row_dict(file_id)
    if record is None:
        logger.error(f"[ingest] run_embed: file {file_id} missing")
        return
    investigation_id = record["investigation_id"]
    inv = get_investigation(investigation_id)
    if inv is None:
        logger.error(f"[ingest] run_embed: investigation {investigation_id} missing")
        return
    index_name = inv["index_name"]

    es = ESClient()
    embed = get_embedding_client()
    batch_size = Config.EMBED_BATCH_SIZE

    # Reset counter at start; if a previous embed errored mid-flight, the
    # full sweep is still cheap on a single file's records.
    _set_status(file_id, "complete", embedded_count=0, vectors_ready=False)

    embedded = 0
    scroll_id: Optional[str] = None
    try:
        # Filter by source_file at the ES level so we only stream this
        # upload's docs, not the whole investigation.
        body = {
            "size": batch_size,
            "_source": ["text", "title"],
            "query": {"term": {"source_file": file_id}},
        }
        resp = es._client.search(index=index_name, body=body, scroll="5m")
        scroll_id = resp.get("_scroll_id")
        while True:
            hits = resp["hits"]["hits"]
            if not hits:
                break
            texts: list[str] = []
            ids:   list[str] = []
            for hit in hits:
                src = hit.get("_source", {})
                t = (src.get("text") or src.get("title") or "")[:2000]
                texts.append(t)
                ids.append(hit["_id"])
            if texts:
                vecs = embed.embed(texts)
                updates = [{"_id": doc_id, "embedding": vec}
                           for doc_id, vec in zip(ids, vecs)]
                done = es.bulk_update_embeddings(index_name, updates)
                embedded += done
                _set_status(file_id, "complete", embedded_count=embedded)
            if not scroll_id:
                break
            resp = es._client.scroll(scroll_id=scroll_id, scroll="5m")
            scroll_id = resp.get("_scroll_id")
    finally:
        if scroll_id:
            try:
                es._client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass

    # Refresh + invalidate vector cache so hybrid search activates for
    # *this file's* docs immediately. The retriever singleton needs the
    # same invalidation as ``embed_docs`` does.
    try:
        es._client.indices.refresh(index=index_name)
    except Exception as e:
        logger.warning(f"[embed_file] refresh failed: {e}")
    try:
        es.invalidate_vector_cache(index_name)
        from src.retrieval.retriever import get_retriever
        retriever = get_retriever()
        if retriever._es_client:
            retriever._es_client.invalidate_vector_cache(index_name)
    except Exception as e:
        logger.warning(f"[embed_file] vector-cache invalidate failed: {e}")

    _set_status(file_id, "complete", embedded_count=embedded, vectors_ready=True)
    logger.info(
        f"[embed_file] {file_id}: embedded {embedded} doc(s) → vectors_ready",
        "magenta",
    )
