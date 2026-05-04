"""Kafka task handlers for the ingestion pipeline.

Two task types, both routed through the ``fast_tasks`` topic (see
``tasking.producer``). The work is IO-bound; the LLM mapping inference is
exactly one short call per file, which is too small to justify a separate
LLM lane.

Importing this module registers the handlers — ``main.py`` does the import
at startup so they're available before the consumer starts.
"""
from __future__ import annotations

from framework.commons.logger import logger

from src.ingestion import pipeline
from src.tasking.registry import register


@register("ingest_file")
def handle_ingest_file(task: dict) -> None:
    """Stage 1 task: parse + propose mapping (or take cache hit).

    Body: ``{"file_id": "...", "investigation_id": "..."}``. The
    investigation_id is informational — the file row already carries it.
    """
    file_id = task.get("file_id")
    if not file_id:
        logger.error("[ingest] handle_ingest_file: missing file_id")
        return
    pipeline.run_parse(file_id)


@register("ingest_continue")
def handle_ingest_continue(task: dict) -> None:
    """Stage 2 task: stream-extract and bulk-index.

    Published by the API after the user confirms the proposed mapping
    (and optionally saves it as a profile). Also self-published from
    ``run_parse`` when a profile cache hit lets us skip review.
    """
    file_id = task.get("file_id")
    if not file_id:
        logger.error("[ingest] handle_ingest_continue: missing file_id")
        return
    pipeline.run_index(file_id)


@register("embed_file")
def handle_embed_file(task: dict) -> None:
    """Stage 3 task: embed only this file's records into the investigation
    index. Lets each upload become hybrid-searchable as soon as it finishes,
    instead of waiting for an all-or-nothing ``embed_docs`` re-run after the
    whole investigation is loaded.
    """
    file_id = task.get("file_id")
    if not file_id:
        logger.error("[ingest] handle_embed_file: missing file_id")
        return
    pipeline.run_embed(file_id)
