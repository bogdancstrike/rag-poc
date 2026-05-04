"""Handler protocol + the universal ``RawRecord`` dataclass.

A *handler* understands one family of file formats (csv, json, xlsx, ...).
Its job is split into four phases the pipeline calls in order:

    1. ``sniff(head)``           — confidence in [0,1] given the first few KB
    2. ``fingerprint(path, options)``
                                 — stable structural hash for profile reuse
    3. ``propose_mapping(path, options)``
                                 — sample records + suggested column→field mapping
    4. ``extract(path, mapping, options)``
                                 — yield ``RawRecord``s lazily; the pipeline
                                   batches them into ES bulk-index calls

All four phases are streaming-safe: handlers MUST NOT load the full file into
memory, since Phase-1 supports multi-GB uploads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Protocol


@dataclass(slots=True)
class RawRecord:
    """One logical record extracted from a file. Becomes one ES doc.

    Only ``text`` is required. Everything else is optional and falls through
    to the corresponding ES doc field via ``ingestion.normalizer``.

    ``raw`` carries the full original record so the UI can display fidelity
    even when the mapping drops fields.
    """
    text:         str
    title:        Optional[str] = None
    created_at:   Optional[str] = None   # ISO8601 string; None = unknown
    author:       Optional[str] = None
    url:          Optional[str] = None
    raw:          dict = field(default_factory=dict)
    record_index: int = 0                # ordinal within file; used for stable _id


@dataclass(slots=True)
class MappingProposal:
    """Returned by ``propose_mapping``. The pipeline either applies this
    directly (profile-cached path) or surfaces it to the UI for confirmation
    (mapping_review status)."""
    columns:           list[str]                # ordered field names from the file
    samples:           list[dict]               # first N records, raw shape
    suggested_mapping: dict                     # see plan §6.3 per format family
    options:           dict                     # delimiter / encoding / etc.
    confidence:        float = 0.0
    rationale:         Optional[str] = None


class FileHandler(Protocol):
    """Stable contract every format handler implements.

    Implementations are stateless — instances are reused across uploads.
    Configuration (delimiter, encoding, ...) flows in via the ``options``
    dict on each call.
    """

    name: str                            # short id, e.g. "csv"
    extensions: tuple[str, ...]          # lowercased, with leading dot
    mime_types: tuple[str, ...]

    def sniff(self, head: bytes) -> float:
        """Return [0,1] confidence that this handler should parse the file,
        based on the first 8-64 KB of content. The dispatcher uses the
        highest-confidence handler whose value clears a threshold."""

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        """Return a sha256 hex string identifying the file's *structure*
        (e.g. set of CSV headers + delimiter), or None if no useful
        cross-file reuse is meaningful (e.g. PDF). Used as the cache key
        for ``ParserProfile``."""

    def propose_mapping(self, path: Path, options: dict) -> MappingProposal:
        """Inspect the head of the file and return a mapping proposal.
        May call the LLM (typically once per file). The pipeline caches the
        result via the profile system to avoid repeat LLM calls on identical
        structures."""

    def extract(self, path: Path, mapping: dict, options: dict) -> Iterator[RawRecord]:
        """Stream records lazily. Caller batches; this method must not
        materialize the full file."""

    def estimate_records(self, path: Path, options: dict) -> Optional[int]:
        """Best-effort total record count for progress UI. Return None when
        unknowable cheaply (e.g. it would require a full scan)."""
