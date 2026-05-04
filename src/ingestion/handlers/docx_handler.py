"""DOCX handler — paragraph-level extraction via ``python-docx``.

DOCX files are zip containers; each top-level ``Paragraph`` becomes a
candidate record. Heading paragraphs (style starting with ``Heading``) act
as titles for the records that follow until the next heading — which lets
the data-exploration table show meaningful titles instead of "—" or the
first sentence of body text.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator, Optional

from framework.commons.logger import logger

from src.ingestion.handlers import register
from src.ingestion.handlers.base import FileHandler, MappingProposal, RawRecord


_DOCX_MAGIC = b"PK\x03\x04"   # zip header — same as XLSX, so we *also* check
                              # for ``word/document.xml`` in the head.


class DocxHandler:
    """``.docx`` Word documents — one record per paragraph (or per section)."""
    name = "docx"
    extensions = (".docx",)
    mime_types = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # ── Sniff ───────────────────────────────────────────────────────────────

    def sniff(self, head: bytes) -> float:
        """Zip signature + presence of ``word/document.xml`` is a near-certain
        DOCX. Returning 0.9 keeps us above the 0.5 threshold without
        accidentally claiming priority over XLSX (which also starts with
        the zip magic but holds ``xl/workbook.xml``)."""
        if not head.startswith(_DOCX_MAGIC):
            return 0.0
        return 0.9 if b"word/document.xml" in head[:16384] else 0.0

    # ── Options ─────────────────────────────────────────────────────────────

    def _resolve_options(self, path: Path, options: dict) -> dict:
        opts = dict(options or {})
        # "paragraph" yields one record per paragraph (default — fine-grained
        # for retrieval). "section" groups paragraphs under each heading
        # into a single record (better for short docs). "full_text" keeps the
        # whole document as one record.
        opts.setdefault("chunking", "paragraph")
        # Default 0 → no silent drops. Empty paragraphs are still skipped
        # because they carry no information after strip().
        opts.setdefault("min_chars", 0)
        return opts

    # ── Fingerprint ─────────────────────────────────────────────────────────

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        """No useful cross-file structural reuse for arbitrary .docx; we
        still emit a chunking-keyed hash so a per-format profile carrying
        edited options can be saved."""
        opts = self._resolve_options(path, options)
        return hashlib.sha256(f"docx:{opts['chunking']}".encode("utf-8")).hexdigest()

    # ── Mapping proposal ────────────────────────────────────────────────────

    def propose_mapping(self, path: Path, options: dict) -> MappingProposal:
        from src.config import Config
        opts = self._resolve_options(path, options)
        samples: list[dict] = []
        for i, rec in enumerate(
            self._iter_records(path, opts, limit=Config.INGEST_SAMPLE_RECORDS)
        ):
            samples.append({
                "title": rec.title,
                "text": rec.text[:300] + ("…" if len(rec.text) > 300 else ""),
            })
        return MappingProposal(
            columns=["title", "text"],
            samples=samples,
            suggested_mapping={
                "chunking":  opts["chunking"],
                "min_chars": opts["min_chars"],
            },
            options=opts,
            confidence=0.6,
            rationale=(
                "DOCX paragraphs become records; nearest preceding heading "
                "becomes their title."
            ),
        )

    # ── Streaming extract ───────────────────────────────────────────────────

    def extract(self, path: Path, mapping: dict, options: dict) -> Iterator[RawRecord]:
        opts = self._resolve_options(path, options)
        if mapping:
            for k in ("chunking", "min_chars"):
                if k in mapping and mapping[k] is not None:
                    opts[k] = mapping[k]
        yield from self._iter_records(path, opts)

    def _iter_records(self, path: Path, opts: dict,
                      limit: Optional[int] = None) -> Iterator[RawRecord]:
        try:
            from docx import Document
        except ImportError as e:
            logger.error(f"[docx] python-docx not installed: {e}")
            return
        try:
            doc = Document(str(path))
        except Exception as e:
            logger.warning(f"[docx] open failed for {path.name}: {e}")
            return

        chunking  = opts.get("chunking", "paragraph")
        min_chars = opts.get("min_chars", 0)
        if chunking == "full_text":
            chunks = [(para.text or "").strip() for para in doc.paragraphs]
            text = "\n".join(c for c in chunks if c).strip()
            if text and len(text) >= min_chars and (limit is None or limit > 0):
                title = next((c for c in chunks if c), None)
                yield RawRecord(
                    text=text,
                    title=title,
                    raw={"mode": "full_text", "paragraph_count": len(chunks)},
                    record_index=0,
                )
            return

        current_heading: Optional[str] = None
        section_buf: list[str] = []
        idx       = 0
        emitted   = 0

        def _flush_section():
            """Yield the buffered section as a single record."""
            nonlocal idx, emitted, section_buf
            if not section_buf:
                return None
            text = "\n".join(section_buf).strip()
            section_buf = []
            if not text or len(text) < min_chars:
                return None
            return RawRecord(
                text=text,
                title=current_heading,
                raw={"section": current_heading or "(no heading)"},
                record_index=idx,
            )

        for para in doc.paragraphs:
            text = (para.text or "").strip()
            style = (getattr(para.style, "name", "") or "")
            is_heading = style.lower().startswith("heading")

            if is_heading:
                # Emit the previous section (in section mode) before
                # switching headings.
                if chunking == "section":
                    rec = _flush_section()
                    if rec is not None:
                        yield rec
                        idx += 1
                        emitted += 1
                        if limit is not None and emitted >= limit:
                            return
                current_heading = text or current_heading
                continue

            if not text:
                continue

            if chunking == "paragraph":
                if len(text) < min_chars:
                    continue
                yield RawRecord(
                    text=text,
                    title=current_heading,
                    raw={"paragraph": text[:500],
                         "section": current_heading or None},
                    record_index=idx,
                )
                idx += 1
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            else:   # section
                section_buf.append(text)

        # Flush trailing section
        if chunking == "section":
            rec = _flush_section()
            if rec is not None:
                yield rec

    # ── Estimate ────────────────────────────────────────────────────────────

    def estimate_records(self, path: Path, options: dict) -> Optional[int]:
        try:
            from docx import Document
            doc = Document(str(path))
            opts = self._resolve_options(path, options)
            if opts.get("chunking") == "full_text":
                return 1
            return len(doc.paragraphs)
        except Exception:
            return None


register(DocxHandler())
