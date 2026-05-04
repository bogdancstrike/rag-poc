"""Text / Markdown / log handler with line-pattern inference.

Three operating modes, picked at ``propose_mapping`` time:

  - ``regex``       — known line pattern detected (Telegram chat, Apache log,
                      syslog, generic ``[ts] author: msg``). Each matching
                      line is one record; named groups become fields.
  - ``paragraph``   — split on blank-line runs. Default for prose / markdown.
  - ``line``        — each non-empty line is one record. Use for short logs
                      or messages where blank lines are rare.
  - ``whole_text``  — emit the complete file as one record. Useful when a text
                      document should stay intact for review/search.

The inferred pattern is stored in the parser profile, so re-uploading the
same kind of log file reuses the same regex without LLM involvement.
"""
from __future__ import annotations

import hashlib
import re
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


# ── Built-in patterns ─────────────────────────────────────────────────────────
# Each entry is (regex, name). The first one matching ≥70% of sample lines wins.
# Order matters: more specific patterns first. Use named groups so the
# normalizer can pick fields up directly.

_BUILTIN_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Telegram-style: [2024-05-12 18:42:01] @user: message
    (re.compile(
        r"^\[(?P<created_at>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\]\s+"
        r"(?P<author>@?\S+)\s*:\s*(?P<text>.*)$"
    ), "telegram_chat"),
    # Apache combined log:
    # 73.215.42.18 - - [12/Jun/2024:08:14:22 +0000] "GET /path HTTP/1.1" 200 1247 "-" "UA"
    (re.compile(
        r'^(?P<author>\S+)\s+\S+\s+\S+\s+'
        r'\[(?P<created_at>[^\]]+)\]\s+'
        r'"(?P<text>[A-Z]+\s+[^"]*?)"\s+\d+\s+\S+'
    ), "apache_access"),
    # syslog: Jun 12 08:14:22 host process[pid]: message
    (re.compile(
        r"^(?P<created_at>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
        r"(?P<author>\S+)\s+(?P<text>.*)$"
    ), "syslog"),
]


def _try_pattern_inference(lines: list[str]) -> Optional[tuple[str, str]]:
    """Return (regex_pattern_str, name) if ≥70% of non-empty lines match a
    built-in pattern, else None."""
    nonempty = [ln for ln in lines if ln.strip()]
    if len(nonempty) < 5:
        return None
    sample = nonempty[:200]
    for pat, name in _BUILTIN_PATTERNS:
        hits = sum(1 for ln in sample if pat.match(ln))
        if hits / len(sample) >= 0.7:
            return pat.pattern, name
    return None


class TextHandler:
    """Plain-text / markdown / log handler."""
    name = "text"
    extensions = (".txt", ".md", ".log")
    mime_types = ("text/plain", "text/markdown")

    # ── Sniff ───────────────────────────────────────────────────────────────

    def sniff(self, head: bytes) -> float:
        """0.4 if the head is decodable text without binary garbage. We
        keep this *low* so JSON/CSV beat us when their extensions are missing
        — text is the catch-all."""
        if not head:
            return 0.0
        if b"\x00" in head[:4096]:
            return 0.0
        try:
            head.decode(_detect_encoding(head), errors="strict")
            return 0.4
        except Exception:
            return 0.0

    # ── Options ─────────────────────────────────────────────────────────────

    def _resolve_options(self, path: Path, options: dict) -> dict:
        """Defaults are deliberately *non-lossy*:

        - ``min_chars=0``  — keep every record regardless of length. The user
                              can raise this in the review drawer if they want
                              short noise lines filtered out.
        - ``drop_empty=True`` — only drop blank-after-strip lines, which carry
                                no information.
        - ``regex_keep_unmatched=True`` — in regex mode, lines that don't match
                                the pattern are still emitted as raw-text
                                records (with ``raw.unmatched=True``) so the
                                user never silently loses content.
        """
        opts = dict(options or {})
        if "encoding" not in opts:
            try:
                with path.open("rb") as f:
                    head = f.read(64 * 1024)
                opts["encoding"] = _detect_encoding(head)
            except OSError:
                opts["encoding"] = _FALLBACK_ENCODING
        opts.setdefault("min_chars", 0)
        opts.setdefault("drop_empty", True)
        opts.setdefault("regex_keep_unmatched", True)
        return opts

    # ── Mode inference + fingerprint ────────────────────────────────────────

    def _infer_mode(self, path: Path, opts: dict) -> dict:
        """Pick mode + regex by sampling the head. Stored in options for
        downstream calls. Idempotent — caller-provided ``mode``/``regex``
        wins."""
        if opts.get("mode"):
            return opts
        try:
            with path.open("r", encoding=opts["encoding"], errors="replace") as f:
                head_lines = []
                for _ in range(200):
                    line = f.readline()
                    if not line:
                        break
                    head_lines.append(line.rstrip("\n"))
        except OSError as e:
            logger.warning(f"[text] mode-inference read failed: {e}")
            opts["mode"] = "paragraph"
            return opts

        inferred = _try_pattern_inference(head_lines)
        if inferred:
            opts["mode"] = "regex"
            opts["regex"] = inferred[0]
            opts["regex_name"] = inferred[1]
            return opts

        # Markdown? — default to paragraph mode regardless.
        if path.suffix.lower() == ".md":
            opts["mode"] = "paragraph"
            return opts

        # If most lines are short and there are few blank lines, treat as
        # line-mode. Otherwise paragraph.
        nonempty = [l for l in head_lines if l.strip()]
        blank_ratio = (len(head_lines) - len(nonempty)) / max(1, len(head_lines))
        avg_len = sum(len(l) for l in nonempty) / max(1, len(nonempty))
        if blank_ratio < 0.05 and avg_len < 200:
            opts["mode"] = "line"
        else:
            opts["mode"] = "paragraph"
        return opts

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        """For text the only structural signal is the inferred mode + regex.
        Two log files with the same mode + same regex share a profile."""
        opts = self._resolve_options(path, options)
        opts = self._infer_mode(path, opts)
        canonical = opts["mode"] + "\n" + (opts.get("regex") or "")
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ── Mapping proposal ────────────────────────────────────────────────────

    def propose_mapping(self, path: Path, options: dict) -> MappingProposal:
        from src.config import Config
        opts = self._resolve_options(path, options)
        opts = self._infer_mode(path, opts)
        samples: list[dict] = []
        for i, rec in enumerate(self._iter_records(path, opts, limit=Config.INGEST_SAMPLE_RECORDS)):
            samples.append(rec.raw if rec.raw else {"text": rec.text})
        # Mapping for text is trivial — fields are baked into the regex/mode
        # and the extractor populates RawRecord directly. We expose a token
        # mapping for UI symmetry with the tabular handlers.
        suggested = {
            "mode": opts["mode"],
            "regex": opts.get("regex"),
            "min_chars": opts["min_chars"],
        }
        return MappingProposal(
            columns=["text", "created_at", "author"] if opts["mode"] == "regex" else ["text"],
            samples=samples,
            suggested_mapping=suggested,
            options=opts,
            confidence=0.6 if opts["mode"] == "regex" else 0.4,
            rationale=(
                f"Regex pattern `{opts.get('regex_name', 'inferred')}` matched ≥70% of head lines."
                if opts["mode"] == "regex" else
                f"Falling back to {opts['mode']} mode."
            ),
        )

    # ── Iteration helpers ───────────────────────────────────────────────────

    def _iter_records(self, path: Path, opts: dict,
                      limit: Optional[int] = None) -> Iterator[RawRecord]:
        mode = opts["mode"]
        if mode == "regex":
            yield from self._iter_regex(path, opts, limit)
        elif mode == "line":
            yield from self._iter_line(path, opts, limit)
        elif mode == "whole_text":
            yield from self._iter_whole_text(path, opts, limit)
        else:
            yield from self._iter_paragraph(path, opts, limit)

    def _iter_regex(self, path: Path, opts: dict,
                    limit: Optional[int]) -> Iterator[RawRecord]:
        try:
            pat = re.compile(opts["regex"])
        except re.error as e:
            logger.warning(f"[text] invalid regex; falling back to line mode: {e}")
            yield from self._iter_line(path, opts, limit)
            return
        min_chars = opts.get("min_chars", 0)
        keep_unmatched = opts.get("regex_keep_unmatched", True)
        drop_empty     = opts.get("drop_empty", True)
        with path.open("r", encoding=opts["encoding"], errors="replace") as f:
            count = 0
            for idx, line in enumerate(f):
                line = line.rstrip("\n")
                stripped = line.strip()
                if drop_empty and not stripped:
                    continue
                m = pat.match(line)
                if m:
                    gd = m.groupdict()
                    text = gd.get("text") or line
                    if len(text) < min_chars:
                        # Skip only when the user has *explicitly* asked for
                        # a min length. With min_chars=0 (default) nothing
                        # is dropped here.
                        continue
                    yield RawRecord(
                        text=text,
                        title=gd.get("title"),
                        created_at=gd.get("created_at"),
                        author=gd.get("author"),
                        url=gd.get("url"),
                        raw={**gd, "_line": line},
                        record_index=idx,
                    )
                elif keep_unmatched:
                    # Pattern miss → emit the raw line so we never silently
                    # drop content. Flagged in raw so callers / UI can
                    # distinguish "parsed" vs "fallback" records.
                    if len(stripped) < min_chars:
                        continue
                    yield RawRecord(
                        text=stripped,
                        raw={"_line": line, "unmatched": True},
                        record_index=idx,
                    )
                else:
                    continue
                count += 1
                if limit is not None and count >= limit:
                    return

    def _iter_line(self, path: Path, opts: dict,
                   limit: Optional[int]) -> Iterator[RawRecord]:
        min_chars = opts.get("min_chars", 0)
        drop_empty = opts.get("drop_empty", True)
        with path.open("r", encoding=opts["encoding"], errors="replace") as f:
            count = 0
            for idx, line in enumerate(f):
                stripped = line.rstrip("\n").strip()
                if drop_empty and not stripped:
                    continue
                if len(stripped) < min_chars:
                    continue
                yield RawRecord(
                    text=stripped,
                    raw={"line": stripped},
                    record_index=idx,
                )
                count += 1
                if limit is not None and count >= limit:
                    return

    def _iter_paragraph(self, path: Path, opts: dict,
                        limit: Optional[int]) -> Iterator[RawRecord]:
        """Yield blank-line-separated paragraphs. We assemble paragraphs in a
        rolling buffer so we never materialize the whole file."""
        min_chars = opts.get("min_chars", 0)
        buf: list[str] = []
        emitted = 0
        idx = 0
        with path.open("r", encoding=opts["encoding"], errors="replace") as f:
            for line in f:
                if line.strip():
                    buf.append(line.rstrip("\n"))
                else:
                    if buf:
                        para = "\n".join(buf).strip()
                        buf.clear()
                        if len(para) >= min_chars:
                            yield RawRecord(text=para, raw={"paragraph": para},
                                            record_index=idx)
                            idx += 1
                            emitted += 1
                            if limit is not None and emitted >= limit:
                                return
            if buf:
                para = "\n".join(buf).strip()
                if len(para) >= min_chars:
                    yield RawRecord(text=para, raw={"paragraph": para}, record_index=idx)

    def _iter_whole_text(self, path: Path, opts: dict,
                         limit: Optional[int]) -> Iterator[RawRecord]:
        if limit is not None and limit <= 0:
            return
        min_chars = opts.get("min_chars", 0)
        drop_empty = opts.get("drop_empty", True)
        text = path.read_text(encoding=opts["encoding"], errors="replace").strip()
        if drop_empty and not text:
            return
        if len(text) < min_chars:
            return
        yield RawRecord(text=text, raw={"text": text, "mode": "whole_text"}, record_index=0)

    # ── Extract (pipeline-facing) ──────────────────────────────────────────

    def extract(self, path: Path, mapping: dict, options: dict) -> Iterator[RawRecord]:
        opts = self._resolve_options(path, options)
        # mapping may carry user-edited mode/regex from the confirm step.
        if mapping:
            for k in ("mode", "regex", "min_chars"):
                if k in mapping and mapping[k] is not None:
                    opts[k] = mapping[k]
        opts = self._infer_mode(path, opts)
        yield from self._iter_records(path, opts)

    # ── Estimate ────────────────────────────────────────────────────────────

    def estimate_records(self, path: Path, options: dict) -> Optional[int]:
        # Cheap upper bound: number of non-empty lines. Paragraph mode
        # over-estimates, but it's only for the progress UI.
        try:
            opts = self._resolve_options(path, options)
            opts = self._infer_mode(path, opts)
            if opts.get("mode") == "whole_text":
                return 1
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


register(TextHandler())
