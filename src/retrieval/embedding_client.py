"""Embedding client — GPU via TEI (production) or in-process CPU fastembed (fallback).

Behaviour is decided by ``Config.EMBED_BASE_URL``:

  - Set (e.g. ``http://localhost:8080``) → POSTs to a Text Embeddings
    Inference (TEI) HTTP server. This is the production path; TEI runs
    on the GPU box alongside vLLM via ``docker-compose-llm.yml``.
  - Empty → loads ``fastembed.TextEmbedding`` in-process and embeds on
    CPU. Used by the test suite and dev boxes that don't run TEI.

Public API is identical in both modes::

    client = get_embedding_client()
    vecs   = client.embed(["text one", "text two"])   # list[list[float]]
    vec    = client.embed_one("single text")           # list[float]

The same singleton is reused across the app, so first-call latency
(model load on CPU mode, HTTP warmup on TEI mode) only happens once per
process.
"""
from __future__ import annotations

from typing import Optional

from framework.commons.logger import logger
from src.config import Config


# How many texts to send per HTTP call to TEI. TEI batches internally, so
# this only affects request count, not GPU throughput. 32 is a comfortable
# size for typical request payloads (each text ≤ 2000 chars).
_TEI_BATCH = 32

# Per-text length cap before sending. bge-large-en-v1.5 is trained on
# 512-token sequences; 2000 chars covers that comfortably.
_TEXT_TRUNCATE = 2000


class EmbeddingClient:
    """Dual-mode embedding wrapper. See module docstring."""

    def __init__(self):
        # Lazy: neither backend is initialised until the first ``embed`` call.
        self._fastembed_model = None     # type: Optional[object]
        self._mode: Optional[str] = None  # "tei" | "fastembed"

    # ── Public API ──────────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one float vector per input.

        Texts are truncated to ``_TEXT_TRUNCATE`` chars before embedding.
        On the TEI path, batching is done client-side so the HTTP payload
        stays bounded; TEI batches internally too.
        """
        if not texts:
            return []
        truncated = [t[:_TEXT_TRUNCATE] for t in texts]
        mode = self._resolve_mode()
        if mode == "tei":
            return self._embed_tei(truncated)
        return self._embed_fastembed(truncated)

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    # ── Mode resolution ─────────────────────────────────────────────────────

    def _resolve_mode(self) -> str:
        """Decide the backend on first use and stick to it for the process
        lifetime. ``EMBED_BASE_URL`` takes priority; otherwise fastembed."""
        if self._mode is not None:
            return self._mode
        if Config.EMBED_BASE_URL:
            self._mode = "tei"
            logger.info(
                f"[embed] Using TEI HTTP backend at {Config.EMBED_BASE_URL} "
                f"(model {Config.EMBED_MODEL}, dims {Config.EMBED_DIMS})"
            )
        else:
            self._mode = "fastembed"
            logger.info(
                "[embed] EMBED_BASE_URL unset → falling back to in-process "
                "fastembed (CPU). Set EMBED_BASE_URL to use a GPU TEI server."
            )
        return self._mode

    # ── TEI HTTP backend ────────────────────────────────────────────────────

    def _embed_tei(self, texts: list[str]) -> list[list[float]]:
        """POST to TEI's ``/embed`` endpoint in client-side batches.

        TEI returns ``[[v1...], [v2...], ...]`` with the same order as
        the input. We use the native ``/embed`` route (not the OpenAI
        ``/v1/embeddings`` shim) because it's marginally faster and the
        payload is simpler.
        """
        import requests
        out: list[list[float]] = []
        url = f"{Config.EMBED_BASE_URL}/embed"
        for start in range(0, len(texts), _TEI_BATCH):
            batch = texts[start:start + _TEI_BATCH]
            try:
                r = requests.post(
                    url,
                    json={"inputs": batch},
                    timeout=Config.EMBED_TIMEOUT,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.error(f"[embed] TEI call failed for batch {start}-{start+len(batch)}: {e}")
                raise
            # TEI returns either ``[[v...]]`` (default) or
            # ``{"data": [{"embedding": [...]}, ...]}`` if launched in
            # OpenAI-compat mode. Handle both for forward-compat.
            if isinstance(data, list):
                out.extend(data)
            elif isinstance(data, dict) and "data" in data:
                out.extend(item["embedding"] for item in data["data"])
            else:
                raise RuntimeError(f"[embed] Unexpected TEI response shape: {type(data).__name__}")
        return out

    # ── Fastembed fallback ──────────────────────────────────────────────────

    def _get_fastembed_model(self):
        """Lazy-load ``fastembed.TextEmbedding`` on first use."""
        if self._fastembed_model is None:
            try:
                from fastembed import TextEmbedding
                logger.info(
                    f"[embed] Loading fastembed {Config.EMBED_MODEL} "
                    "(first use — one-time download if not cached)"
                )
                self._fastembed_model = TextEmbedding(
                    model_name=Config.EMBED_MODEL,
                    cache_dir=Config.EMBED_CACHE_DIR,
                )
                logger.info(
                    f"[embed] fastembed ready: {Config.EMBED_MODEL} "
                    f"({Config.EMBED_DIMS}-dim)"
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load fastembed model {Config.EMBED_MODEL!r}: {e}"
                ) from e
        return self._fastembed_model

    def _embed_fastembed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_fastembed_model()
        return [vec.tolist() for vec in model.embed(texts)]


# Module-level singleton
_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    """Return the module-level EmbeddingClient singleton."""
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
