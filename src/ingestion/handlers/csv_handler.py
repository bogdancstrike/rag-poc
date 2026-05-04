"""CSV / TSV handler with auto-detected delimiter and encoding.

Streaming: Python's stdlib ``csv`` reader iterates row-by-row over the
underlying text stream — a multi-GB CSV is parsed without materializing.
Encoding is detected once over a 64 KB head sample (charset-normalizer);
delimiter is sniffed via ``csv.Sniffer`` with a hard fallback to comma.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from typing import Iterator, Optional

from charset_normalizer import from_bytes
from framework.commons.logger import logger

from src.ingestion.handlers import register
from src.ingestion.handlers.base import FileHandler, MappingProposal, RawRecord


_DEFAULT_DELIMITER = ","
_SNIFF_BYTES = 64 * 1024
_FALLBACK_ENCODING = "utf-8"


def _detect_encoding(head: bytes) -> str:
    """Best-effort encoding detection. Falls back to utf-8 on failure —
    we treat encoding as a hint, never an authority."""
    try:
        result = from_bytes(head).best()
        return result.encoding if result else _FALLBACK_ENCODING
    except Exception:
        return _FALLBACK_ENCODING


def _detect_delimiter(sample: str) -> str:
    """Auto-detect the column separator.

    csv.Sniffer's character-frequency heuristic mis-detects when the body
    contains many quoted commas inside `;`-delimited fields. To make this
    robust, we first examine the *header line* — by convention it has no
    quoted content — and pick the candidate delimiter that produces the
    most columns there. Sniffer is the fallback.
    """
    candidates = (",", ";", "\t", "|")
    first_line = sample.split("\n", 1)[0]
    if first_line:
        counts = {d: first_line.count(d) for d in candidates}
        best = max(counts, key=lambda d: counts[d])
        if counts[best] >= 1:
            # Validate: at least 50% of the next 10 lines should have the
            # same column count under this delimiter. Otherwise fall through
            # to Sniffer.
            lines = sample.split("\n")[1:11]
            if lines:
                expected = first_line.count(best) + 1
                ok = sum(1 for ln in lines if ln.strip() and ln.count(best) + 1 == expected)
                if ok / max(1, sum(1 for ln in lines if ln.strip())) >= 0.5:
                    return best
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return _DEFAULT_DELIMITER


class CsvHandler:
    """Tabular handler — each row becomes one ``RawRecord``."""
    name = "csv"
    extensions = (".csv", ".tsv")
    mime_types = ("text/csv", "text/tab-separated-values")

    # ── Sniff ───────────────────────────────────────────────────────────────

    def sniff(self, head: bytes) -> float:
        """Heuristic: a CSV-ish file has at least 2 newlines in the head and
        >= 2 columns separated by a recognizable delimiter on most lines.
        Returns 0.6 on a confident match — extension match (1.0) is the
        primary path; this is the fallback for misnamed files."""
        if not head or b"\x00" in head[:4096]:   # binary file
            return 0.0
        try:
            text = head.decode(_detect_encoding(head), errors="replace")
        except Exception:
            return 0.0
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return 0.0
        delim = _detect_delimiter("\n".join(lines[:20]))
        col_counts = [len(ln.split(delim)) for ln in lines[:20]]
        if not col_counts or max(col_counts) < 2:
            return 0.0
        # Most rows should have the same column count for a real CSV.
        most_common = max(set(col_counts), key=col_counts.count)
        consistency = col_counts.count(most_common) / len(col_counts)
        return 0.65 if consistency >= 0.7 else 0.0

    # ── Options resolution ──────────────────────────────────────────────────

    def _resolve_options(self, path: Path, options: dict) -> dict:
        """Fill in delimiter / encoding / has_header from a head sample.

        Pre-set values in ``options`` win — the user's confirmation is the
        source of truth once they've reviewed the proposed mapping.
        """
        opts = dict(options or {})
        if "encoding" not in opts or "delimiter" not in opts:
            with path.open("rb") as f:
                head = f.read(_SNIFF_BYTES)
            opts.setdefault("encoding", _detect_encoding(head))
            try:
                sample_text = head.decode(opts["encoding"], errors="replace")
            except Exception:
                sample_text = head.decode("utf-8", errors="replace")
            opts.setdefault("delimiter", _detect_delimiter(sample_text))
        opts.setdefault("has_header", True)
        return opts

    # ── Fingerprint ─────────────────────────────────────────────────────────

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        """sha256(sorted(lower(strip(headers))) + delimiter).

        Two CSVs with the same header set + delimiter share a fingerprint
        regardless of column order — so re-orderings of the same export
        format reuse the saved profile.
        """
        opts = self._resolve_options(path, options)
        if not opts.get("has_header", True):
            return None
        try:
            headers = self._read_headers(path, opts)
        except Exception as e:
            logger.warning(f"[csv] fingerprint header read failed: {e}")
            return None
        if not headers:
            return None
        canonical = "\t".join(sorted(h.strip().lower() for h in headers))
        return hashlib.sha256(
            (canonical + "\n" + opts["delimiter"]).encode("utf-8")
        ).hexdigest()

    def _read_headers(self, path: Path, opts: dict) -> list[str]:
        """Read just the header row. Cheap — opens, reads one line, closes."""
        with path.open("r", encoding=opts["encoding"], errors="replace", newline="") as f:
            reader = csv.reader(f, delimiter=opts["delimiter"])
            return next(reader, [])

    # ── Mapping proposal ────────────────────────────────────────────────────

    def propose_mapping(self, path: Path, options: dict) -> MappingProposal:
        """Read first ``INGEST_SAMPLE_RECORDS+1`` rows, suggest a mapping.

        Heuristic: the column with the longest average string length is the
        most likely ``text`` field. The LLM (called from
        ``ingestion.llm_mapping``) refines this — but the pipeline can fall
        back to the heuristic when the LLM is unavailable.
        """
        from src.config import Config
        opts = self._resolve_options(path, options)
        sample_rows: list[dict] = []
        headers: list[str] = []
        with path.open("r", encoding=opts["encoding"], errors="replace", newline="") as f:
            reader = csv.reader(f, delimiter=opts["delimiter"])
            if opts.get("has_header", True):
                headers = next(reader, [])
            else:
                first = next(reader, [])
                headers = [f"col_{i}" for i in range(len(first))]
                sample_rows.append(dict(zip(headers, first)))
            for i, row in enumerate(reader):
                if i >= Config.INGEST_SAMPLE_RECORDS:
                    break
                sample_rows.append(dict(zip(headers, row)))

        suggested = self._heuristic_mapping(headers, sample_rows)
        return MappingProposal(
            columns=headers,
            samples=sample_rows,
            suggested_mapping=suggested,
            options=opts,
            confidence=0.5,
            rationale="Heuristic — longest text column picked as `text`.",
        )

    def _heuristic_mapping(self, headers: list[str], samples: list[dict]) -> dict:
        """Pick the column with the longest mean value as ``text``; map a
        column whose name looks like ``date`` / ``time`` / ``created`` to
        ``created_at``; map ``title`` / ``subject`` / ``name`` to ``title``;
        ``author`` / ``user`` / ``from`` to ``author``; ``url`` / ``link`` to
        ``url``."""
        if not headers or not samples:
            return {"text": headers[0] if headers else None}

        avg_lens = {h: 0 for h in headers}
        for row in samples:
            for h in headers:
                v = row.get(h, "") or ""
                avg_lens[h] += len(str(v))
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
        """Yield one ``RawRecord`` per row.

        ``mapping`` keys are the canonical fields (text/title/...); values are
        the source column names from the file. Empty mapping values fall
        back gracefully (text → JSON of full row).
        """
        opts = self._resolve_options(path, options)
        text_col = mapping.get("text")
        title_col = mapping.get("title")
        date_col = mapping.get("created_at")
        author_col = mapping.get("author")
        url_col = mapping.get("url")

        with path.open("r", encoding=opts["encoding"], errors="replace", newline="") as f:
            reader = csv.reader(f, delimiter=opts["delimiter"])
            headers = (next(reader, []) if opts.get("has_header", True) else None)
            if headers is None:
                first = next(reader, [])
                headers = [f"col_{i}" for i in range(len(first))]
                yield self._row_to_record(0, headers, first, text_col, title_col,
                                          date_col, author_col, url_col)
                start = 1
            else:
                start = 0
            for i, row in enumerate(reader, start=start):
                if not row:
                    continue
                yield self._row_to_record(i, headers, row, text_col, title_col,
                                          date_col, author_col, url_col)

    def _row_to_record(self, idx: int, headers: list[str], row: list[str],
                       text_col: Optional[str], title_col: Optional[str],
                       date_col:  Optional[str], author_col: Optional[str],
                       url_col:   Optional[str]) -> RawRecord:
        """Build one record, padding short rows so a missing trailing column
        doesn't IndexError. Long rows (more cells than headers) get the
        overflow stored under ``__extra_<n>`` so we never silently lose data.
        """
        d: dict = {}
        for i, h in enumerate(headers):
            d[h] = row[i] if i < len(row) else ""
        if len(row) > len(headers):
            for i in range(len(headers), len(row)):
                d[f"__extra_{i}"] = row[i]
        text = (d.get(text_col, "") if text_col else "") or ""
        if not text:
            text = " ".join(str(v) for v in d.values() if v)
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
        """Cheap newline count; over-estimates by 1 (header) but good enough
        for a progress bar. Bounded at 5M lines to avoid pathological scans."""
        try:
            count = 0
            with path.open("rb") as f:
                for _ in f:
                    count += 1
                    if count > 5_000_000:
                        return None
            return max(0, count - (1 if options.get("has_header", True) else 0))
        except OSError:
            return None


register(CsvHandler())
