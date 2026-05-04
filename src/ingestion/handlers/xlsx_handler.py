"""XLSX handler — streams via openpyxl ``read_only=True``.

All visible sheets are ingested. Each row becomes one record; the source
sheet name is recorded in ``raw.__sheet`` so the user can filter on it
later in the Data Exploration table. The fingerprint covers all sheet
headers so workbooks with the same shape collide on the profile cache.

Mixed-shape workbooks (different headers per sheet) still ingest cleanly
— each sheet is parsed against its own headers.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator, Optional

from framework.commons.logger import logger

from src.ingestion.handlers import register
from src.ingestion.handlers.base import FileHandler, MappingProposal, RawRecord


_XLSX_MAGIC = b"PK\x03\x04"   # XLSX is a ZIP archive


class XlsxHandler:
    name = "xlsx"
    extensions = (".xlsx",)
    mime_types = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ── Sniff ───────────────────────────────────────────────────────────────

    def sniff(self, head: bytes) -> float:
        """ZIP magic + presence of 'xl/workbook.xml' string in the first 16KB
        is a reliable XLSX signature. (Plain ZIP would lack the latter.)"""
        if not head.startswith(_XLSX_MAGIC):
            return 0.0
        return 0.9 if b"xl/workbook.xml" in head[:16384] else 0.4

    def _open_workbook(self, path: Path):
        from openpyxl import load_workbook
        # read_only=True gives us a streaming row iterator without loading
        # the full sheet into memory; data_only=True returns formula values
        # rather than the formula text itself.
        return load_workbook(filename=str(path), read_only=True, data_only=True)

    # ── Fingerprint ─────────────────────────────────────────────────────────

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        """sha256 of every sheet's name + sorted-lowercased headers.

        Two workbooks with the same sheet structure (same names + same
        header sets) share a fingerprint, regardless of column order.
        """
        try:
            wb = self._open_workbook(path)
        except Exception as e:
            logger.warning(f"[xlsx] open failed: {e}")
            return None
        try:
            parts: list[str] = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                headers = self._read_headers(ws)
                if not headers:
                    continue
                parts.append(sheet_name + ":" + "\t".join(
                    sorted(h.strip().lower() for h in headers)
                ))
        finally:
            wb.close()
        if not parts:
            return None
        canonical = "\n".join(parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_headers(ws) -> list[str]:
        for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            return [str(c) if c is not None else f"col_{i}" for i, c in enumerate(row)]
        return []

    # ── Options ─────────────────────────────────────────────────────────────

    def _resolve_options(self, path: Path, options: dict) -> dict:
        """Sheet name (defaults to active/first) + has_header flag."""
        opts = dict(options or {})
        opts.setdefault("has_header", True)
        # ``sheet`` is left None to mean "first sheet" — resolved at call time.
        opts.setdefault("sheet", None)
        return opts

    # ── Mapping proposal ────────────────────────────────────────────────────

    def propose_mapping(self, path: Path, options: dict) -> MappingProposal:
        """Sample rows from the *first non-empty* sheet for the proposal.

        The mapping is then applied uniformly to every sheet at extract time.
        Multi-sheet workbooks with diverging headers still ingest, but
        unmapped columns simply land in ``raw`` for that sheet's rows.
        """
        from src.config import Config
        opts = self._resolve_options(path, options)
        wb = self._open_workbook(path)
        try:
            preview_sheet = wb.sheetnames[0]
            opts["sheet_names"] = list(wb.sheetnames)
            headers: list[str] = []
            samples: list[dict] = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                row_iter = ws.iter_rows(values_only=True)
                if opts["has_header"]:
                    first = next(row_iter, None)
                    if first is None:
                        continue
                    headers = [str(c) if c is not None else f"col_{i}"
                               for i, c in enumerate(first)]
                preview_sheet = sheet_name
                for i, row in enumerate(row_iter):
                    if i >= Config.INGEST_SAMPLE_RECORDS:
                        break
                    if not headers:
                        headers = [f"col_{j}" for j in range(len(row))]
                    samples.append({h: ("" if v is None else str(v))
                                    for h, v in zip(headers, row)})
                if samples:
                    break   # first non-empty sheet wins for the preview
            opts["preview_sheet"] = preview_sheet
        finally:
            wb.close()
        suggested = self._heuristic_mapping(headers, samples)
        sheet_count = len(opts.get("sheet_names", []))
        rationale = (
            "Heuristic — longest text column picked as `text`."
            + (f" Workbook has {sheet_count} sheet(s); all will be ingested."
               if sheet_count > 1 else "")
        )
        return MappingProposal(
            columns=headers, samples=samples, suggested_mapping=suggested,
            options=opts, confidence=0.5, rationale=rationale,
        )

    def _heuristic_mapping(self, headers: list[str], samples: list[dict]) -> dict:
        if not headers or not samples:
            return {"text": headers[0] if headers else None}
        avg_lens = {h: 0 for h in headers}
        for row in samples:
            for h in headers:
                avg_lens[h] += len(str(row.get(h, "") or ""))
        text_col = max(avg_lens, key=lambda h: avg_lens[h])

        def pick(*aliases: str) -> Optional[str]:
            for h in headers:
                low = h.lower()
                for a in aliases:
                    if a in low:
                        return h
            return None

        return {
            "text":       text_col,
            "title":      pick("title", "subject", "name"),
            "created_at": pick("created", "date", "time", "posted", "timestamp"),
            "author":     pick("author", "user", "from", "by"),
            "url":        pick("url", "link", "permalink"),
        }

    # ── Streaming extract ───────────────────────────────────────────────────

    def extract(self, path: Path, mapping: dict, options: dict) -> Iterator[RawRecord]:
        """Yield records from EVERY sheet in the workbook.

        Sheet name is recorded in ``raw.__sheet`` so downstream filters
        can scope to one sheet. The global record_index counter is
        contiguous across sheets so stable ES ``_id``s never collide.
        """
        opts = self._resolve_options(path, options)
        text_col = mapping.get("text")
        title_col = mapping.get("title")
        date_col = mapping.get("created_at")
        author_col = mapping.get("author")
        url_col = mapping.get("url")

        wb = self._open_workbook(path)
        global_idx = 0
        try:
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                row_iter = ws.iter_rows(values_only=True)
                headers: list[str] = []
                if opts["has_header"]:
                    first = next(row_iter, None)
                    if first is None:
                        continue
                    headers = [str(c) if c is not None else f"col_{i}"
                               for i, c in enumerate(first)]
                else:
                    first = next(row_iter, None)
                    if first is None:
                        continue
                    headers = [f"col_{i}" for i in range(len(first))]
                    rec = self._row_to_record(
                        global_idx, headers, first, text_col, title_col,
                        date_col, author_col, url_col, sheet_name,
                    )
                    yield rec
                    global_idx += 1
                for row in row_iter:
                    if not row or all(c is None for c in row):
                        continue
                    rec = self._row_to_record(
                        global_idx, headers, row, text_col, title_col,
                        date_col, author_col, url_col, sheet_name,
                    )
                    yield rec
                    global_idx += 1
        finally:
            wb.close()

    def _row_to_record(self, idx: int, headers: list[str], row,
                       text_col: Optional[str], title_col: Optional[str],
                       date_col:  Optional[str], author_col: Optional[str],
                       url_col:   Optional[str],
                       sheet_name: Optional[str] = None) -> RawRecord:
        d = {h: ("" if v is None else str(v)) for h, v in zip(headers, row)}
        if sheet_name:
            d["__sheet"] = sheet_name
        text = d.get(text_col, "") if text_col else ""
        if not text:
            text = " ".join(v for k, v in d.items() if k != "__sheet" and v)
        return RawRecord(
            text=text,
            title=d.get(title_col) if title_col else None,
            created_at=d.get(date_col) if date_col else None,
            author=d.get(author_col) if author_col else None,
            url=d.get(url_col) if url_col else None,
            raw=d,
            record_index=idx,
        )

    # ── Estimate ────────────────────────────────────────────────────────────

    def estimate_records(self, path: Path, options: dict) -> Optional[int]:
        """Sum ``max_row - 1`` across every sheet (header offset). Returns
        None if any sheet doesn't expose ``max_row`` in read-only mode."""
        try:
            wb = self._open_workbook(path)
            try:
                opts = self._resolve_options(path, options)
                total = 0
                for sheet_name in wb.sheetnames:
                    mr = wb[sheet_name].max_row
                    if mr is None:
                        return None
                    total += max(0, mr - (1 if opts["has_header"] else 0))
                return total
            finally:
                wb.close()
        except Exception:
            return None


register(XlsxHandler())
