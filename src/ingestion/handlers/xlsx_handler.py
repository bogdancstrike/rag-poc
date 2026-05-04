"""XLSX handler — streams via openpyxl ``read_only=True``.

Each sheet is treated as an independent CSV-like body of records. The
fingerprint folds in sheet names so two workbooks with identical sheets
can share a profile, but a workbook reshuffled across sheets cannot.

Only the *first* sheet is parsed by default — multi-sheet ingestion is a
future enhancement (we'd publish one ingest_continue per sheet). The plan
acknowledges this; flagged in TODO.md if revisited.
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
        """sha256(sheet_name + headers_lower) for the active sheet.

        Active-sheet only for now to match the active-sheet-only extract().
        """
        opts = self._resolve_options(path, options)
        try:
            wb = self._open_workbook(path)
        except Exception as e:
            logger.warning(f"[xlsx] open failed: {e}")
            return None
        try:
            sheet_name = opts.get("sheet") or wb.sheetnames[0]
            ws = wb[sheet_name]
            headers = self._read_headers(ws)
        finally:
            wb.close()
        if not headers:
            return None
        canonical = sheet_name + "\n" + "\t".join(sorted(h.strip().lower() for h in headers))
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
        from src.config import Config
        opts = self._resolve_options(path, options)
        wb = self._open_workbook(path)
        try:
            sheet_name = opts.get("sheet") or wb.sheetnames[0]
            opts["sheet"] = sheet_name
            ws = wb[sheet_name]
            headers: list[str] = []
            samples: list[dict] = []
            row_iter = ws.iter_rows(values_only=True)
            if opts["has_header"]:
                first = next(row_iter, None)
                if first is None:
                    return MappingProposal([], [], {"text": None}, opts, 0.0, "Empty sheet")
                headers = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(first)]
            for i, row in enumerate(row_iter):
                if i >= Config.INGEST_SAMPLE_RECORDS:
                    break
                if not headers:
                    headers = [f"col_{j}" for j in range(len(row))]
                samples.append({h: ("" if v is None else str(v))
                                for h, v in zip(headers, row)})
        finally:
            wb.close()
        suggested = self._heuristic_mapping(headers, samples)
        return MappingProposal(
            columns=headers, samples=samples, suggested_mapping=suggested,
            options=opts, confidence=0.5,
            rationale="Heuristic — longest text column picked as `text`.",
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
        opts = self._resolve_options(path, options)
        text_col = mapping.get("text")
        title_col = mapping.get("title")
        date_col = mapping.get("created_at")
        author_col = mapping.get("author")
        url_col = mapping.get("url")

        wb = self._open_workbook(path)
        try:
            sheet_name = opts.get("sheet") or wb.sheetnames[0]
            ws = wb[sheet_name]
            row_iter = ws.iter_rows(values_only=True)
            headers: list[str]
            if opts["has_header"]:
                first = next(row_iter, None)
                if first is None:
                    return
                headers = [str(c) if c is not None else f"col_{i}"
                           for i, c in enumerate(first)]
                start = 0
            else:
                first = next(row_iter, None)
                if first is None:
                    return
                headers = [f"col_{i}" for i in range(len(first))]
                yield self._row_to_record(0, headers, first, text_col, title_col,
                                          date_col, author_col, url_col)
                start = 1
            for idx, row in enumerate(row_iter, start=start):
                if not row or all(c is None for c in row):
                    continue
                yield self._row_to_record(idx, headers, row, text_col, title_col,
                                          date_col, author_col, url_col)
        finally:
            wb.close()

    def _row_to_record(self, idx: int, headers: list[str], row,
                       text_col: Optional[str], title_col: Optional[str],
                       date_col:  Optional[str], author_col: Optional[str],
                       url_col:   Optional[str]) -> RawRecord:
        d = {h: ("" if v is None else str(v)) for h, v in zip(headers, row)}
        text = d.get(text_col, "") if text_col else ""
        if not text:
            text = " ".join(v for v in d.values() if v)
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
        try:
            wb = self._open_workbook(path)
            try:
                opts = self._resolve_options(path, options)
                sheet_name = opts.get("sheet") or wb.sheetnames[0]
                ws = wb[sheet_name]
                # ``max_row`` is None in read-only mode for some files; fall
                # back to None rather than scanning.
                mr = ws.max_row
                if mr is None:
                    return None
                return max(0, mr - (1 if opts["has_header"] else 0))
            finally:
                wb.close()
        except Exception:
            return None


register(XlsxHandler())
