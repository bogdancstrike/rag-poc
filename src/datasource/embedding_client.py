"""Embedding client using fastembed (CPU-only ONNX runtime).

Wraps BAAI/bge-m3 (1024-dim, multilingual) for document and query embedding.
The model is lazy-loaded on first use — startup is unaffected.
GPU is never touched; the RTX 3080 stays owned entirely by SGLang.

Usage:
    from src.datasource.embedding_client import get_embedding_client
    client = get_embedding_client()
    vecs = client.embed(["text one", "text two"])   # list[list[float]]
    vec  = client.embed_one("single text")           # list[float]
"""
from framework.commons.logger import logger
from src.config import Config


class EmbeddingClient:
    """Singleton wrapper around fastembed TextEmbedding."""

    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                logger.info(f"[embed] Loading {Config.EMBED_MODEL} (first use — one-time download if not cached)")
                self._model = TextEmbedding(
                    model_name=Config.EMBED_MODEL,
                    cache_dir=Config.EMBED_CACHE_DIR,
                )
                logger.info(f"[embed] Model ready: {Config.EMBED_MODEL} ({Config.EMBED_DIMS}-dim)")
            except Exception as e:
                raise RuntimeError(f"Failed to load embedding model {Config.EMBED_MODEL!r}: {e}") from e
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one float vector per input.

        Texts are truncated to 2000 chars before embedding (~512 tokens for bge-m3).
        This captures the full semantic signal for typical OSINT document excerpts
        while keeping memory and latency predictable.
        """
        if not texts:
            return []
        truncated = [t[:2000] for t in texts]
        model = self._get_model()
        return [vec.tolist() for vec in model.embed(truncated)]

    def embed_one(self, text: str) -> list[float]:
        """Embed a single string. Convenience wrapper around embed()."""
        return self.embed([text])[0]


# Module-level singleton
_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """Return the module-level EmbeddingClient singleton."""
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
