"""Handler registry — maps file → handler via extension/mime/content sniff.

Handler modules register themselves at import time via ``register()``. The
package's ``__init__`` (this file) imports them so registration happens
exactly once when ``src.ingestion`` is first loaded.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from framework.commons.logger import logger

from src.ingestion.handlers.base import FileHandler


# ── Registry ─────────────────────────────────────────────────────────────────

_HANDLERS: dict[str, FileHandler] = {}


def register(handler: FileHandler) -> FileHandler:
    """Register a handler under its ``name``. Idempotent — re-registering the
    same name overwrites (useful in tests)."""
    _HANDLERS[handler.name] = handler
    return handler


def get(name: str) -> Optional[FileHandler]:
    return _HANDLERS.get(name)


def all_handlers() -> list[FileHandler]:
    return list(_HANDLERS.values())


# ── Dispatch ─────────────────────────────────────────────────────────────────

# How many bytes to read for content-based sniffing. 64 KB is more than
# enough for headers/magic-bytes detection without paging in a full block.
_SNIFF_HEAD_BYTES = 64 * 1024


def get_for(path: Path, mime_type: Optional[str] = None) -> Optional[FileHandler]:
    """Pick the best handler for a file, in order:

    1. Extension match (cheapest).
    2. MIME hint match.
    3. Content sniff: read first ``_SNIFF_HEAD_BYTES`` and pick the handler
       returning the highest confidence ≥ 0.5.

    Returns None if nothing clears the threshold — the pipeline records the
    upload as an error in that case.
    """
    ext = path.suffix.lower()

    # Extension fast-path
    for h in _HANDLERS.values():
        if ext in h.extensions:
            return h

    # MIME hint
    if mime_type:
        for h in _HANDLERS.values():
            if mime_type in h.mime_types:
                return h

    # Content sniff
    try:
        with path.open("rb") as f:
            head = f.read(_SNIFF_HEAD_BYTES)
    except OSError as e:
        logger.warning(f"[ingest] sniff read failed for {path}: {e}")
        return None

    best: tuple[float, Optional[FileHandler]] = (0.0, None)
    for h in _HANDLERS.values():
        try:
            conf = h.sniff(head)
        except Exception as e:
            logger.warning(f"[ingest] handler {h.name!r} sniff raised: {e}")
            conf = 0.0
        if conf > best[0]:
            best = (conf, h)
    return best[1] if best[0] >= 0.5 else None


# ── Eager-import handler modules so they register on package import ───────────

from src.ingestion.handlers import (  # noqa: E402, F401
    csv_handler,
    json_handler,
    xlsx_handler,
    text_handler,
    pdf_handler,
    docx_handler,
    html_handler,
)
