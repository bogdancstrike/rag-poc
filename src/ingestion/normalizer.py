"""``RawRecord`` → ES doc shape (single source of truth).

The investigation index is dynamically-mapped, but we deliberately keep the
shape uniform so retrieval/embedding/enrichment code never needs special
cases per source. See plan §3.2.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from src.config import Config
from src.ingestion.handlers.base import RawRecord


def stable_doc_id(file_id: str, record_index: int) -> str:
    """Deterministic ES ``_id``.

    Re-running ingestion (after a crash, after a mapping edit, etc.) upserts
    onto the same ``_id`` and is therefore idempotent. The hash also avoids
    collisions across files because ``file_id`` is a UUID.
    """
    return hashlib.sha256(f"{file_id}:{record_index}".encode("utf-8")).hexdigest()


def normalize(rec: RawRecord, file_id: str, filename: str) -> dict:
    """Convert a ``RawRecord`` to the canonical ES doc.

    Truncates ``text`` to ``Config.INGEST_TEXT_TRUNCATE`` chars to bound
    indexing/enrichment cost on pathologically large cells. The full
    original row is preserved in ``raw`` so uploaded tabular data remains
    visible and searchable by source column.

    Title fallback: scraped/searched documents always have a ``title``,
    but uploaded records often don't (CSV row, JSON object without a
    title-ish key). The Data Exploration table looks visually broken when
    half the rows have a title and half don't. So we *always* emit a
    title — derived from the first ~80 chars of text when no real one
    was mapped, or from the filename + record index when the text is also
    empty. The ``title_synthetic`` flag lets the UI treat fallback titles
    differently if it ever wants to (e.g. dim them).
    """
    text = (rec.text or "").strip()
    if len(text) > Config.INGEST_TEXT_TRUNCATE:
        text = text[:Config.INGEST_TEXT_TRUNCATE]

    raw = rec.raw or {}

    title = (rec.title or "").strip() or None
    title_synthetic = False
    if not title:
        title_synthetic = True
        if text:
            title = _summarise_for_title(text)
        else:
            title = f"{filename} #{rec.record_index}"

    doc: dict = {
        "text":            text,
        "title":           title,
        "title_synthetic": title_synthetic,
        "created_at":      rec.created_at,
        "author":          rec.author,
        "url":             rec.url,
        "source":          f"upload:{filename}#{rec.record_index}",
        "source_file":     file_id,
        "source_index":    rec.record_index,
        "raw":             raw,
    }
    # Drop None values to keep ES mapping clean.
    return {k: v for k, v in doc.items() if v is not None}


def _summarise_for_title(text: str, cap: int = 80) -> str:
    """Cut a one-line preview from arbitrary text for use as a title.

    Strategy: take the first non-empty line, collapse internal whitespace,
    truncate to ~80 chars on a word boundary, and append an ellipsis when
    we cut. Never returns an empty string for non-empty input.
    """
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    one_line = " ".join(first_line.split())
    if len(one_line) <= cap:
        return one_line
    cut = one_line[:cap]
    last_space = cut.rfind(" ")
    if last_space > 40:    # only break on space if there's room
        cut = cut[:last_space]
    return cut + "…"
