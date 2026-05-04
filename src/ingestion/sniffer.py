"""Format detection — wraps the handler registry.

The registry already does sniff-by-extension/mime/content; this module is a
thin facade so callers don't reach into ``handlers/`` directly. It also
exposes the canonical accepted-format list used by the frontend dropzones.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.ingestion.handlers import all_handlers, get_for
from src.ingestion.handlers.base import FileHandler


def detect(path: Path, mime_type: Optional[str] = None) -> Optional[FileHandler]:
    """Pick the best handler for ``path``. Thin wrapper around
    ``handlers.get_for`` to keep callers off the registry directly."""
    return get_for(path, mime_type)


def accepted_formats() -> dict:
    """Return the user-facing list of accepted formats. Used by the frontend
    to render the dropzone hint (``accept`` attribute + visible chip list).

    Output is sorted by handler name so the chip order is stable.
    """
    by_name: dict[str, dict] = {}
    for h in all_handlers():
        by_name[h.name] = {
            "name": h.name,
            "extensions": list(h.extensions),
            "mime_types": list(h.mime_types),
        }
    return {
        "handlers": [by_name[k] for k in sorted(by_name)],
        # Flat list for the HTML <input accept=""> attribute.
        "accept_string": ",".join(
            sorted({ext for h in all_handlers() for ext in h.extensions})
        ),
    }
