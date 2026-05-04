"""Storage abstraction for uploaded original files.

Phase-1 implementation is local disk; the ``Storage`` Protocol exists so a
later S3 / MinIO backend can be dropped in without touching the pipeline.

Layout on disk (LocalDiskStorage):

    ${UPLOADS_DIR}/<investigation_id>/<file_id>/
        original.<ext>   — exact bytes the user uploaded
        meta.json        — {filename, size, sha256, mime, uploaded_at}

The investigation_id directory is created lazily on first write and removed
when ``delete_for_investigation`` is called (used by investigation-delete).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional, Protocol

from framework.commons.logger import logger

from src.config import Config


# ── Public dataclass returned by Storage.write ────────────────────────────────

class StoredFile:
    """Metadata about a freshly-stored file. Plain object (not a dataclass) to
    avoid the dataclass import overhead in this hot path."""

    __slots__ = ("uri", "size", "sha256", "path")

    def __init__(self, uri: str, size: int, sha256: str, path: Path) -> None:
        self.uri = uri
        self.size = size
        self.sha256 = sha256
        self.path = path

    def to_dict(self) -> dict:
        return {"uri": self.uri, "size": self.size, "sha256": self.sha256, "path": str(self.path)}


class StorageError(RuntimeError):
    """Raised on any storage-layer failure (write, read, delete)."""


class FileTooLargeError(StorageError):
    """Raised when an upload exceeds ``Config.UPLOADS_MAX_SIZE_BYTES``."""


# ── Protocol ─────────────────────────────────────────────────────────────────

class Storage(Protocol):
    """Stable interface every storage backend must implement.

    Implementations MUST stream — they may not buffer the entire upload in
    memory, because Phase-1 supports multi-GB files.
    """

    def write(self, investigation_id: str, file_id: str, filename: str,
              stream: BinaryIO) -> StoredFile: ...

    def open(self, investigation_id: str, file_id: str) -> BinaryIO: ...

    def stat(self, investigation_id: str, file_id: str) -> StoredFile: ...

    def write_meta(self, investigation_id: str, file_id: str, meta: dict) -> None: ...

    def read_meta(self, investigation_id: str, file_id: str) -> Optional[dict]: ...

    def delete(self, investigation_id: str, file_id: str) -> None: ...

    def delete_for_investigation(self, investigation_id: str) -> None: ...

    def path_for(self, investigation_id: str, file_id: str) -> Path:
        """Best-effort filesystem path for handlers that *must* mmap or seek.
        Backends without real paths (S3) should download to a temp file."""
        ...


# ── LocalDiskStorage ──────────────────────────────────────────────────────────

class LocalDiskStorage:
    """Files-on-disk implementation of ``Storage``.

    Streaming writes compute sha256 + size in a single pass — important for
    multi-GB files where re-reading would double the IO cost. The unit of
    storage is the *file directory* (``<root>/<inv>/<id>/``) so that the
    original upload and its sidecar ``meta.json`` stay co-located.
    """

    # 4 MiB read chunk: large enough to amortize syscall overhead without
    # holding too much in memory under concurrent uploads.
    CHUNK_BYTES = 4 * 1024 * 1024

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = Path(root or Config.UPLOADS_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Path helpers ────────────────────────────────────────────────────────

    def _dir(self, investigation_id: str, file_id: str) -> Path:
        return self.root / investigation_id / file_id

    def _find_original(self, dir_path: Path) -> Optional[Path]:
        """Locate the single ``original.<ext>`` inside a file directory."""
        if not dir_path.is_dir():
            return None
        for entry in dir_path.iterdir():
            if entry.name.startswith("original"):
                return entry
        return None

    def path_for(self, investigation_id: str, file_id: str) -> Path:
        original = self._find_original(self._dir(investigation_id, file_id))
        if original is None:
            raise StorageError(f"original file not found for {investigation_id}/{file_id}")
        return original

    # ── Streaming write ─────────────────────────────────────────────────────

    def write(self, investigation_id: str, file_id: str, filename: str,
              stream: BinaryIO) -> StoredFile:
        """Stream-write ``stream`` to disk while computing sha256 + size.

        Enforces ``Config.UPLOADS_MAX_SIZE_BYTES`` (0 = unlimited). On size
        violation the partial file is removed before raising.

        The file is named ``original.<ext>`` (extension copied from the
        user-supplied filename) so handlers can sniff by extension when
        content-sniffing is ambiguous.
        """
        max_bytes = Config.UPLOADS_MAX_SIZE_BYTES
        ext = Path(filename).suffix.lower()
        target_dir = self._dir(investigation_id, file_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"original{ext}"

        hasher = hashlib.sha256()
        total = 0
        try:
            with target_path.open("wb") as out:
                while True:
                    chunk = stream.read(self.CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        # Tear down the partial write before raising so the
                        # caller doesn't have to.
                        out.close()
                        try: target_path.unlink()
                        except FileNotFoundError: pass
                        raise FileTooLargeError(
                            f"upload exceeds {max_bytes} bytes "
                            f"(seen {total} so far)"
                        )
                    hasher.update(chunk)
                    out.write(chunk)
        except FileTooLargeError:
            raise
        except Exception as e:
            # Best-effort cleanup of the half-written file
            try: target_path.unlink()
            except FileNotFoundError: pass
            raise StorageError(f"write failed: {e}") from e

        stored = StoredFile(
            uri=f"file://{target_path}",
            size=total,
            sha256=hasher.hexdigest(),
            path=target_path,
        )
        logger.info(
            f"[storage] wrote {investigation_id}/{file_id} "
            f"size={total} sha256={stored.sha256[:12]}..."
        )
        return stored

    # ── Read / introspect ───────────────────────────────────────────────────

    def open(self, investigation_id: str, file_id: str) -> BinaryIO:
        return self.path_for(investigation_id, file_id).open("rb")

    def stat(self, investigation_id: str, file_id: str) -> StoredFile:
        path = self.path_for(investigation_id, file_id)
        meta = self.read_meta(investigation_id, file_id) or {}
        size = path.stat().st_size
        return StoredFile(
            uri=f"file://{path}",
            size=size,
            sha256=meta.get("sha256", ""),
            path=path,
        )

    # ── Sidecar meta ────────────────────────────────────────────────────────

    def write_meta(self, investigation_id: str, file_id: str, meta: dict) -> None:
        target_dir = self._dir(investigation_id, file_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        meta = {**meta, "saved_at": datetime.now(timezone.utc).isoformat()}
        (target_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    def read_meta(self, investigation_id: str, file_id: str) -> Optional[dict]:
        meta_path = self._dir(investigation_id, file_id) / "meta.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text())
        except Exception as e:
            logger.warning(f"[storage] meta read failed for {investigation_id}/{file_id}: {e}")
            return None

    # ── Delete ──────────────────────────────────────────────────────────────

    def delete(self, investigation_id: str, file_id: str) -> None:
        target_dir = self._dir(investigation_id, file_id)
        if not target_dir.exists():
            return
        try:
            shutil.rmtree(target_dir)
        except Exception as e:
            raise StorageError(f"delete failed for {investigation_id}/{file_id}: {e}") from e

    def delete_for_investigation(self, investigation_id: str) -> None:
        """Remove the entire per-investigation upload tree.

        Called when the investigation itself is deleted. Best-effort: a missing
        directory is not an error.
        """
        target_dir = self.root / investigation_id
        if not target_dir.exists():
            return
        try:
            shutil.rmtree(target_dir)
            logger.info(f"[storage] purged uploads tree for investigation {investigation_id}")
        except Exception as e:
            logger.warning(f"[storage] purge failed for {investigation_id}: {e}")


# ── Module-level singleton ────────────────────────────────────────────────────

_storage: Optional[Storage] = None


def get_storage() -> Storage:
    """Return the process-wide storage backend. Currently always LocalDisk."""
    global _storage
    if _storage is None:
        _storage = LocalDiskStorage()
    return _storage
