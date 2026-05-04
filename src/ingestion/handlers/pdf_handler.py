"""PDF handler — text extraction via ``pypdf``.

OCR for scanned PDFs is *not* in Phase 2; pypdf returns empty strings for
image-only pages and we surface a record-count of zero in that case so the
UI shows "no extractable text" rather than silently swallowing the upload.

Two chunking modes:
  - ``page``       — one record per PDF page (default; sensible for reports).
  - ``paragraph``  — split each page on blank-line runs; finer-grained for
                      retrieval but more records per file.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator, Optional

from framework.commons.logger import logger

from src.ingestion.handlers import register
from src.ingestion.handlers.base import FileHandler, MappingProposal, RawRecord


_PDF_MAGIC = b"%PDF-"


class PdfHandler:
    """PDF → ``RawRecord`` per page (or per paragraph)."""
    name = "pdf"
    extensions = (".pdf",)
    mime_types = ("application/pdf",)

    # ── Sniff ───────────────────────────────────────────────────────────────

    def sniff(self, head: bytes) -> float:
        """PDF magic bytes are unmistakable."""
        return 0.95 if head.startswith(_PDF_MAGIC) else 0.0

    # ── Options ─────────────────────────────────────────────────────────────

    def _resolve_options(self, path: Path, options: dict) -> dict:
        opts = dict(options or {})
        opts.setdefault("chunking", "page")     # "page" | "paragraph"
        opts.setdefault("min_chars", 20)
        return opts

    # ── Fingerprint ─────────────────────────────────────────────────────────

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        """PDFs vary too much by content for a useful structural hash; we
        return a per-handler constant + chosen chunking so a per-format
        profile (with optional user-edited mapping) is still possible.
        """
        opts = self._resolve_options(path, options)
        canonical = "pdf:" + opts["chunking"]
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ── Mapping proposal ────────────────────────────────────────────────────

    def propose_mapping(self, path: Path, options: dict) -> MappingProposal:
        """Show the first 3 pages (truncated) as samples.

        For PDFs the "mapping" is just the chunking + min_chars settings —
        there are no columns. We return the same shape as the text handler
        for UI consistency.
        """
        from src.config import Config
        opts = self._resolve_options(path, options)
        samples: list[dict] = []
        for i, rec in enumerate(self._iter_records(
            path, opts, limit=Config.INGEST_SAMPLE_RECORDS,
        )):
            samples.append({
                "page": rec.raw.get("page"),
                "text": rec.text[:300] + ("…" if len(rec.text) > 300 else ""),
            })
        non_empty = [s for s in samples if s.get("text")]
        rationale = (
            "Text-extractable PDF (one record per page). Scanned PDFs without "
            "OCR yield empty text; consider OCR pre-processing if this file "
            "is image-only."
            if non_empty else
            "PDF appears image-only or unparseable — pypdf extracted no text. "
            "OCR would be required (not in Phase 2)."
        )
        return MappingProposal(
            columns=["page", "text"],
            samples=samples,
            suggested_mapping={
                "chunking":  opts["chunking"],
                "min_chars": opts["min_chars"],
            },
            options=opts,
            confidence=0.6 if non_empty else 0.1,
            rationale=rationale,
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
        """Stream records lazily.

        We iterate ``PdfReader.pages`` rather than materialising all pages
        because pypdf decompresses each page on access — keeping the working
        set small even for thick PDFs.
        """
        try:
            from pypdf import PdfReader
        except ImportError as e:
            logger.error(f"[pdf] pypdf not installed: {e}")
            return

        try:
            reader = PdfReader(str(path))
        except Exception as e:
            logger.warning(f"[pdf] open failed for {path.name}: {e}")
            return

        chunking  = opts.get("chunking", "page")
        min_chars = opts.get("min_chars", 0)
        emitted   = 0
        idx       = 0
        title_meta = None
        try:
            title_meta = (reader.metadata or {}).get("/Title")
        except Exception:
            title_meta = None

        for page_no, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as e:
                logger.warning(f"[pdf] page {page_no} extract failed: {e}")
                text = ""
            text = text.strip()
            if not text or len(text) < min_chars:
                continue

            if chunking == "paragraph":
                # Split the page on blank-line runs; preserves paragraph
                # boundaries while letting the same file produce 5x as many
                # retrieval-sized records.
                for para in (p.strip() for p in text.split("\n\n")):
                    if not para or len(para) < min_chars:
                        continue
                    yield RawRecord(
                        text=para,
                        title=str(title_meta) if title_meta else None,
                        raw={"page": page_no, "paragraph": para[:500]},
                        record_index=idx,
                    )
                    idx += 1
                    emitted += 1
                    if limit is not None and emitted >= limit:
                        return
            else:
                yield RawRecord(
                    text=text,
                    title=str(title_meta) if title_meta else None,
                    raw={"page": page_no, "text": text[:500]},
                    record_index=idx,
                )
                idx += 1
                emitted += 1
                if limit is not None and emitted >= limit:
                    return

    # ── Estimate ────────────────────────────────────────────────────────────

    def estimate_records(self, path: Path, options: dict) -> Optional[int]:
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            n = len(reader.pages)
            opts = self._resolve_options(path, options)
            # Paragraph mode is hard to estimate without scanning — return
            # page count as a lower bound (over-restrictive but honest).
            return n if opts["chunking"] == "page" else None
        except Exception:
            return None


register(PdfHandler())
