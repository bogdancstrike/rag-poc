"""File-based datasource loader.

Supports JSONL, JSON (array or object), CSV, and plain text files.
Provides in-memory BM25 search via rank_bm25.
"""
import csv
import json
import uuid
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi
from framework.commons.logger import logger


class FileLoader:
    """Loads a corpus file and provides BM25 keyword search over it."""

    def __init__(self, path: str):
        self._path   = Path(path)
        self._chunks: list[dict] = []
        self._bm25:   Optional[BM25Okapi] = None
        self._loaded  = False

    # ── Public API ──────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Read and normalise the corpus file. Must be called before search()."""
        if self._loaded:
            return
        if not self._path.exists():
            logger.warning(f"[file] Corpus not found at {self._path}")
            self._chunks = []
            self._loaded = True
            return

        suffix = self._path.suffix.lower()
        if suffix in (".jsonl", ".ndjson"):
            self._chunks = self._load_jsonl()
        elif suffix == ".json":
            self._chunks = self._load_json()
        elif suffix == ".csv":
            self._chunks = self._load_csv()
        else:
            self._chunks = self._load_text()

        logger.info(f"[file] Loaded {len(self._chunks)} chunks from {self._path}")
        self._build_bm25()
        self._loaded = True

    def search(self, query: str, top_k: int = 8) -> list[dict]:
        """BM25 keyword search over in-memory chunks.

        Returns up to top_k results sorted by score descending.
        Each result: {id, text, score, source, metadata}
        """
        self.load()
        if not self._chunks or self._bm25 is None:
            return []

        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)

        # Pair chunks with scores and sort
        ranked = sorted(
            zip(self._chunks, scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        results = []
        for chunk, score in ranked:
            if score <= 0:
                continue
            results.append({
                **chunk,
                "score":  round(float(score), 4),
                "source": "file",
            })
        return results

    def get_sample(self, n: int = 200) -> list[dict]:
        """Return up to n chunks (deterministic first-n for reproducibility)."""
        self.load()
        return self._chunks[:n]

    def get_stats(self) -> dict:
        self.load()
        return {
            "path":      str(self._path),
            "doc_count": len(self._chunks),
            "loaded":    self._loaded,
        }

    # ── Loaders ─────────────────────────────────────────────────────────────────

    def _load_jsonl(self) -> list[dict]:
        chunks = []
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    chunks.append(self._normalise(obj))
                except json.JSONDecodeError:
                    pass
        return chunks

    def _load_json(self) -> list[dict]:
        with self._path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [self._normalise(obj) for obj in data]
        if isinstance(data, dict):
            return [self._normalise(data)]
        return []

    def _load_csv(self) -> list[dict]:
        chunks = []
        with self._path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                chunks.append(self._normalise(dict(row)))
        return chunks

    def _load_text(self) -> list[dict]:
        """Split plain text by double-newlines (paragraphs)."""
        text = self._path.read_text(encoding="utf-8")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [
            {
                "id":       str(uuid.uuid4()),
                "text":     para,
                "score":    0.0,
                "source":   "file",
                "metadata": {"paragraph_index": i},
            }
            for i, para in enumerate(paragraphs)
        ]

    def _normalise(self, obj: dict) -> dict:
        """Map arbitrary dict fields to the common {id, text, source, metadata} shape."""
        text = (
            obj.get("text")
            or obj.get("content")
            or obj.get("body")
            or obj.get("description")
            or obj.get("summary")
            or " ".join(str(v) for v in obj.values())[:1000]
        )
        doc_id = str(obj.get("id") or obj.get("_id") or uuid.uuid4())
        meta = {k: v for k, v in obj.items() if k not in ("text", "content", "body", "id", "_id")}
        return {
            "id":       doc_id,
            "text":     text,
            "score":    0.0,
            "source":   "file",
            "metadata": meta,
        }

    def _build_bm25(self) -> None:
        """Build BM25 index over tokenised chunk texts."""
        tokenised = [chunk["text"].lower().split() for chunk in self._chunks]
        if tokenised:
            self._bm25 = BM25Okapi(tokenised)
