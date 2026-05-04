"""HTML handler — strip-tags + title detection via ``BeautifulSoup``.

Operates on saved web pages, exported reports, etc. The default chunking is
``article`` mode: prefer ``<article>`` / ``<main>`` if present (most
content-publishing sites have one), fall back to ``<body>``. Each chunk is
one record with ``title`` from ``<title>`` and ``url`` from
``<link rel="canonical">`` if present.
"""
from __future__ import annotations

import hashlib
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


class HtmlHandler:
    """``.html`` / ``.htm`` web pages."""
    name = "html"
    extensions = (".html", ".htm")
    mime_types = ("text/html", "application/xhtml+xml")

    # ── Sniff ───────────────────────────────────────────────────────────────

    def sniff(self, head: bytes) -> float:
        """Look for ``<html``, ``<!DOCTYPE html``, or ``<body`` in the head."""
        if not head:
            return 0.0
        try:
            text = head.decode(_detect_encoding(head), errors="replace").lower()
        except Exception:
            return 0.0
        if "<!doctype html" in text or "<html" in text:
            return 0.85
        if "<body" in text or "<head" in text:
            return 0.6
        return 0.0

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
        # "article" prefers <article>/<main>; "paragraph" splits the body
        # into <p>-level records.
        opts.setdefault("chunking", "article")
        opts.setdefault("min_chars", 40)
        return opts

    # ── Fingerprint ─────────────────────────────────────────────────────────

    def fingerprint(self, path: Path, options: dict) -> Optional[str]:
        opts = self._resolve_options(path, options)
        return hashlib.sha256(f"html:{opts['chunking']}".encode("utf-8")).hexdigest()

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
                "url":   rec.url,
                "text":  rec.text[:300] + ("…" if len(rec.text) > 300 else ""),
            })
        return MappingProposal(
            columns=["title", "url", "text"],
            samples=samples,
            suggested_mapping={
                "chunking":  opts["chunking"],
                "min_chars": opts["min_chars"],
            },
            options=opts,
            confidence=0.7,
            rationale=(
                "HTML body extracted; <title> → title, "
                "<link rel='canonical'> → url. ``article`` mode prefers "
                "<article>/<main> if present."
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
            from bs4 import BeautifulSoup
        except ImportError as e:
            logger.error(f"[html] beautifulsoup4 not installed: {e}")
            return

        try:
            with path.open("r", encoding=opts["encoding"], errors="replace") as f:
                # ``lxml`` is fast and forgiving on malformed HTML — common
                # in archived web pages. Fall back to the stdlib parser if
                # lxml is missing for any reason.
                try:
                    soup = BeautifulSoup(f, "lxml")
                except Exception:
                    f.seek(0)
                    soup = BeautifulSoup(f, "html.parser")
        except OSError as e:
            logger.warning(f"[html] open failed for {path.name}: {e}")
            return

        # Strip script/style tags wholesale — they pollute the text body.
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        page_title = (soup.title.string.strip()
                      if soup.title and soup.title.string else None)
        canonical = None
        link = soup.find("link", rel="canonical")
        if link and link.get("href"):
            canonical = link["href"]

        chunking  = opts.get("chunking", "article")
        min_chars = opts.get("min_chars", 0)

        # Locate the content root.
        root = (soup.find("article")
                or soup.find("main")
                or soup.body
                or soup)

        if chunking == "paragraph":
            # One record per <p> / <li> / <h*> with non-empty text.
            idx = 0
            emitted = 0
            for el in root.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
                text = el.get_text(separator=" ", strip=True)
                if not text or len(text) < min_chars:
                    continue
                yield RawRecord(
                    text=text,
                    title=page_title,
                    url=canonical,
                    raw={"tag": el.name, "snippet": text[:500]},
                    record_index=idx,
                )
                idx += 1
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
        else:
            # ``article`` mode: one record carrying the full body text.
            text = root.get_text(separator="\n", strip=True)
            if text and len(text) >= min_chars:
                yield RawRecord(
                    text=text,
                    title=page_title,
                    url=canonical,
                    raw={"page_title": page_title, "canonical": canonical},
                    record_index=0,
                )

    # ── Estimate ────────────────────────────────────────────────────────────

    def estimate_records(self, path: Path, options: dict) -> Optional[int]:
        opts = self._resolve_options(path, options)
        return 1 if opts.get("chunking") == "article" else None


register(HtmlHandler())
