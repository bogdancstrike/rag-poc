"""Unit tests for LocalDiskStorage — streaming write, sha256, size cap."""
import io
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import hashlib

import pytest

from src.ingestion.storage import (
    FileTooLargeError, LocalDiskStorage,
)


@pytest.fixture
def storage(tmp_path):
    return LocalDiskStorage(root=str(tmp_path / "uploads"))


class TestWrite:

    def test_writes_full_payload(self, storage):
        payload = b"hello world\n" * 1000
        stored = storage.write("inv-1", "file-1", "data.txt", io.BytesIO(payload))
        assert stored.size == len(payload)
        assert stored.sha256 == hashlib.sha256(payload).hexdigest()
        assert stored.path.read_bytes() == payload

    def test_uses_extension_from_filename(self, storage):
        stored = storage.write("inv-1", "file-1", "leaks.csv", io.BytesIO(b"a,b\n1,2\n"))
        assert stored.path.name == "original.csv"

    def test_handles_no_extension(self, storage):
        stored = storage.write("inv-1", "file-1", "weirdfile", io.BytesIO(b"x"))
        assert stored.path.name == "original"

    def test_meta_roundtrip(self, storage):
        storage.write("inv-1", "file-1", "x.txt", io.BytesIO(b"hi"))
        storage.write_meta("inv-1", "file-1", {"filename": "x.txt", "size": 2})
        meta = storage.read_meta("inv-1", "file-1")
        assert meta["filename"] == "x.txt"
        assert "saved_at" in meta

    def test_size_cap_enforced(self, storage, monkeypatch):
        from src.config import Config
        monkeypatch.setattr(Config, "UPLOADS_MAX_SIZE_BYTES", 16, raising=False)
        with pytest.raises(FileTooLargeError):
            storage.write("inv-1", "file-1", "big.bin", io.BytesIO(b"x" * 32))
        # The partial file must be cleaned up
        target_dir = storage._dir("inv-1", "file-1")
        leftover = list(target_dir.glob("original*")) if target_dir.exists() else []
        assert leftover == []


class TestDelete:

    def test_delete_removes_directory(self, storage):
        storage.write("inv-1", "file-1", "x.txt", io.BytesIO(b"hi"))
        assert storage._dir("inv-1", "file-1").exists()
        storage.delete("inv-1", "file-1")
        assert not storage._dir("inv-1", "file-1").exists()

    def test_delete_for_investigation_purges_tree(self, storage):
        storage.write("inv-1", "f-1", "a.txt", io.BytesIO(b"a"))
        storage.write("inv-1", "f-2", "b.txt", io.BytesIO(b"b"))
        storage.delete_for_investigation("inv-1")
        assert not (storage.root / "inv-1").exists()

    def test_delete_missing_is_noop(self, storage):
        # Should not raise
        storage.delete("inv-x", "file-y")
        storage.delete_for_investigation("inv-z")


class TestStreamingHashEqualsFullHash:
    """The streaming write must produce the same sha256 as a single-shot hash
    over the same bytes — this is what gates content-based dedupe."""

    def test_large_payload_hash_matches(self, storage):
        # 5 MB of pseudo-random-ish bytes
        payload = (b"abcdefghijklmnopqrstuvwxyz0123456789" * 145000)[:5 * 1024 * 1024]
        stored = storage.write("inv-1", "file-1", "x.bin", io.BytesIO(payload))
        assert stored.sha256 == hashlib.sha256(payload).hexdigest()
