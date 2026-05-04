"""JSON / JSONL handler.

Two flavors share one handler:
  - JSONL  (``.jsonl``, ``.ndjson``) — one JSON object per line; trivially streamable.
  - JSON   (``.json``)               — top-level array of objects; we stream by
                                       parsing line-by-line when possible
                                       (pretty-printed arrays) or by chunked
                                       decoding via a small SAX-like fallback.

A non-array JSON file (single object) is treated as a one-record file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator, Optional

from charset_normalizer import from_bytes
from framework.commons.logger import logger

from src.ingestion.handlers import register
from src.ingestion.handlers.base import FileHandler, MappingProposal, RawRecord


_FALLBACK_ENCODING = "utf-8"


def _detect_encoding(head: bytes) -> str:
    try:
        result = from_bytes(head).best()
        return result.encoding if result else _FALLBACK_ENCODING
    except Exception:
        return _FALLBACK_ENCODING


def _flavor_for(path: Path) -> str:
    """Decide jsonl vs json by extension, with a content peek for ``.json``
    files that turn out to be JSONL."""
    ext = path.suffix.lower()
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    # peek: if first non-whitespace byte is `{` and second line also starts
    # with `{`, treat as jsonl regardless of extension
    try:
        with path.open("rb") as f:
            head = f.read(4096)
    except OSError:
        return "json"
    text = head.decode(_detect_encoding(head), errors="replace").lstrip()
    if text.startswith("{"):
        # crude: if the head contains a closing-brace newline open-brace
        # pattern, it's probably jsonl
        if "}\n{" in text or "}\r\n{" in text:
            return "jsonl"
    return "json"


class JsonHandler:
    """Records-yielding handler for JSON arrays and JSONL streams."""
    name = "jsonl"
    extensions = (".json", ".jsonl", ".ndjson")
    mime_types = ("application/json", "application/x-ndjson", "application/jsonl")

    # ── Sniff ───────────────────────────────────────────────────────────────

    def sniff(self, head: bytes) -> float:
        """Confidence 0.7 if first non-whitespace char is ``{`` or ``[`` AND
        the head can be partially decoded as JSON."""
        if not head or b"\x00" in head[:4096]:
            return 0.0
        try:
            text = head.decode(_detect_encoding(head), errors="replace").lstrip()
        except Exception:
            return 0.0
        if not text or text[0] not in "[{":
            return 0.0
        # Quick validity probe: try to parse the first line as a JSON object.
        first_line = text.splitlines()[0].strip().rstrip(",")
        if first_line.startswith("{"):
            try:
                json.loads(first_line)
                return 0.75
            except Exception:
                pass
        return 0.55  # array-style — looks JSON-ish but not certain

    # ── Records iteration (shared by fingerprint + propose + extract) ───────

    def _iter_records(self, path: Path, encoding: str,
                      limit: Optional[int] = None) -> Iterator[dict]:
        """Yield top-level dicts. Handles both ``.jsonl`` (one obj/line) and
        ``.json`` (top-level array). Non-dict items are wrapped as
        ``{"value": <item>}`` so downstream code only deals with mappings.
        """
        flavor = _flavor_for(path)
        if flavor == "jsonl":
            yield from self._iter_jsonl(path, encoding, limit)
        else:
            yield from self._iter_json_array(path, encoding, limit)

    def _iter_jsonl(self, path: Path, encoding: str,
                    limit: Optional[int]) -> Iterator[dict]:
        with path.open("r", encoding=encoding, errors="replace") as f:
            count = 0
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"[json] skipping malformed JSONL line: {e}")
                    continue
                if not isinstance(obj, dict):
                    obj = {"value": obj}
                yield obj
                count += 1
                if limit is not None and count >= limit:
                    return

    def _iter_json_array(self, path: Path, encoding: str,
                         limit: Optional[int]) -> Iterator[dict]:
        """Streaming-ish parse for top-level arrays. We avoid pulling the
        full file into memory by reading the entire text only when small;
        for larger arrays we fall back to a brace-counting incremental parser.
        For Phase-1, files small enough to JSON-decode whole are common; the
        incremental path covers larger exports.
        """
        size = path.stat().st_size
        # 32 MB cutoff: below that, full-load is faster and simpler.
        if size <= 32 * 1024 * 1024:
            try:
                with path.open("r", encoding=encoding, errors="replace") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                logger.warning(f"[json] full-load parse failed ({e}); trying incremental")
                yield from self._iter_json_array_incremental(path, encoding, limit)
                return
            if isinstance(data, dict):
                yield data
                return
            if not isinstance(data, list):
                yield {"value": data}
                return
            for i, obj in enumerate(data):
                if limit is not None and i >= limit:
                    return
                yield obj if isinstance(obj, dict) else {"value": obj}
            return
        yield from self._iter_json_array_incremental(path, encoding, limit)

    def _iter_json_array_incremental(self, path: Path, encoding: str,
                                     limit: Optional[int]) -> Iterator[dict]:
        """Brace-balanced top-level-array streamer.

        Reads chunks, locates each top-level ``{...}`` element by tracking
        brace depth (with string-literal awareness so braces inside strings
        don't fool us). Designed to work on machine-generated JSON arrays
        where each element is a flat object — adequate for OSINT exports.
        Documents nested too deeply to fit in working memory will still
        OOM, but this is a Phase-1 acceptable limitation.
        """
        depth = 0
        in_string = False
        escape = False
        buf: list[str] = []
        started = False
        emitted = 0

        with path.open("r", encoding=encoding, errors="replace") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                for ch in chunk:
                    if not started:
                        if ch == "[":
                            started = True
                        continue
                    if in_string:
                        buf.append(ch)
                        if escape:
                            escape = False
                        elif ch == "\\":
                            escape = True
                        elif ch == '"':
                            in_string = False
                        continue
                    if ch == '"':
                        in_string = True
                        buf.append(ch)
                        continue
                    if ch == "{":
                        depth += 1
                        buf.append(ch)
                    elif ch == "}":
                        depth -= 1
                        buf.append(ch)
                        if depth == 0:
                            blob = "".join(buf).strip()
                            buf.clear()
                            if blob.startswith(","):
                                blob = blob[1:].lstrip()
                            try:
                                obj = json.loads(blob)
                            except json.JSONDecodeError:
                                continue
                            if not isinstance(obj, dict):
                                obj = {"value": obj}
                            yield obj
                            emitted += 1
                            if limit is not None and emitted >= limit:
                                return
                    elif depth > 0:
                        buf.append(ch)

    # ── Options ─────────────────────────────────────────────────────────────

    def _resolve_options(self, path: Path, options: dict) -> dict:
        opts = dict(options or {})
        if "encoding" not in opts:
            try:
                with path.open("rb") as f:
                    head = f.read(64 * 1024)
                opts["encoding"] = _detect_encoding(head)
            except OSError:
                opts["encoding"] = _FALLBACK_ENCODING
        opts["flavor"] = _flavor_for(path)
        return opts

    # ── Fingerprint ─────────────────────────────────────────────────────────

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        """Sorted union of top-level keys observed in the first 100 records.
        Two JSONL exports with the same shape collide in the cache."""
        opts = self._resolve_options(path, options)
        keys: set[str] = set()
        for i, rec in enumerate(self._iter_records(path, opts["encoding"], limit=100)):
            keys.update(rec.keys())
            if i >= 99:
                break
        if not keys:
            return None
        canonical = "\n".join(sorted(keys))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ── Mapping proposal ────────────────────────────────────────────────────

    def propose_mapping(self, path: Path, options: dict) -> MappingProposal:
        from src.config import Config
        opts = self._resolve_options(path, options)
        samples: list[dict] = []
        for i, rec in enumerate(self._iter_records(
            path, opts["encoding"], limit=Config.INGEST_SAMPLE_RECORDS
        )):
            samples.append(rec)
        all_keys: set[str] = set()
        for r in samples:
            all_keys.update(r.keys())
        columns = sorted(all_keys)
        suggested = self._heuristic_mapping(columns, samples)
        return MappingProposal(
            columns=columns,
            samples=samples,
            suggested_mapping=suggested,
            options=opts,
            confidence=0.55,
            rationale="Heuristic — longest text key picked as `text`.",
        )

    def _heuristic_mapping(self, keys: list[str], samples: list[dict]) -> dict:
        if not keys or not samples:
            return {"text": keys[0] if keys else None}
        avg_lens = {k: 0 for k in keys}
        for row in samples:
            for k in keys:
                v = row.get(k, "") or ""
                avg_lens[k] += len(str(v))
        text_col = max(avg_lens, key=lambda k: avg_lens[k])

        def pick(*aliases: str) -> Optional[str]:
            for k in keys:
                low = k.lower()
                for a in aliases:
                    if a in low:
                        return k
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

        for idx, rec in enumerate(self._iter_records(path, opts["encoding"])):
            text = ""
            if text_col and text_col in rec:
                text = self._stringify(rec[text_col])
            if not text:
                # Fallback: serialize the whole record so the row is still
                # searchable even when no text column was identified.
                text = json.dumps(rec, ensure_ascii=False)[:5000]
            yield RawRecord(
                text=text,
                title=self._maybe(rec, title_col),
                created_at=self._maybe(rec, date_col),
                author=self._maybe(rec, author_col),
                url=self._maybe(rec, url_col),
                raw=rec,
                record_index=idx,
            )

    @staticmethod
    def _maybe(rec: dict, key: Optional[str]) -> Optional[str]:
        if not key or key not in rec:
            return None
        v = rec[key]
        return None if v is None else str(v)

    @staticmethod
    def _stringify(v) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        return json.dumps(v, ensure_ascii=False)

    # ── Estimate ────────────────────────────────────────────────────────────

    def estimate_records(self, path: Path, options: dict) -> Optional[int]:
        flavor = _flavor_for(path)
        if flavor != "jsonl":
            return None
        try:
            count = 0
            with path.open("rb") as f:
                for line in f:
                    if line.strip():
                        count += 1
                    if count > 5_000_000:
                        return None
            return count
        except OSError:
            return None


register(JsonHandler())
