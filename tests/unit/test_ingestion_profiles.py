"""Unit tests for parser-profile lookup/upsert + the leak_users 2024/2025
fingerprint-equality test that proves the profile cache reuses across
structurally identical files."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from pathlib import Path

import pytest

from src.core.db import init_db, get_engine, Base
from src.ingestion import profiles
from src.ingestion.handlers.csv_handler import CsvHandler


@pytest.fixture(autouse=True)
def fresh_db():
    init_db()
    yield
    Base.metadata.drop_all(bind=get_engine())


@pytest.fixture(scope="module")
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "upload_examples"


class TestProfileFingerprintReuse:

    def test_same_structure_same_fingerprint(self, fixtures_dir):
        h = CsvHandler()
        fp_2024 = h.fingerprint(fixtures_dir / "csv" / "leak_users_2024.csv", {})
        fp_2025 = h.fingerprint(fixtures_dir / "csv" / "leak_users_2025.csv", {})
        assert fp_2024 == fp_2025
        assert fp_2024 is not None

    def test_different_structure_different_fingerprint(self, fixtures_dir):
        h = CsvHandler()
        a = h.fingerprint(fixtures_dir / "csv" / "leak_users_2024.csv", {})
        b = h.fingerprint(fixtures_dir / "csv" / "support_tickets.csv", {})
        c = h.fingerprint(fixtures_dir / "csv" / "intel_reports.csv", {})
        assert len({a, b, c}) == 3


class TestProfileServiceCRUD:

    def test_upsert_then_find(self):
        saved = profiles.upsert(
            handler_name="csv",
            fingerprint="abc123",
            mapping={"text": "body"},
            options={"delimiter": ","},
            sample=[{"body": "x"}],
            name="my-csv",
        )
        assert saved["id"]
        found = profiles.find_by_fingerprint("csv", "abc123")
        assert found is not None
        assert found["mapping"] == {"text": "body"}
        assert found["name"] == "my-csv"

    def test_find_misses_for_unknown_fingerprint(self):
        assert profiles.find_by_fingerprint("csv", "nope") is None

    def test_upsert_updates_existing(self):
        profiles.upsert("csv", "fp1", {"text": "a"}, {"delimiter": ","})
        # Same handler+fp → update, not insert
        profiles.upsert("csv", "fp1", {"text": "b"}, {"delimiter": ";"})
        all_csv = profiles.list_profiles("csv")
        rows = [r for r in all_csv if r["fingerprint"] == "fp1"]
        assert len(rows) == 1
        assert rows[0]["mapping"] == {"text": "b"}
        assert rows[0]["options"] == {"delimiter": ";"}

    def test_mark_used_increments_count(self):
        saved = profiles.upsert("csv", "fp_used", {"text": "a"}, {})
        profiles.mark_used(saved["id"])
        profiles.mark_used(saved["id"])
        again = profiles.find_by_fingerprint("csv", "fp_used")
        assert again["usage_count"] == 2
        assert again["last_used_at"] is not None

    def test_delete_profile(self):
        saved = profiles.upsert("csv", "fp_del", {"text": "a"}, {})
        assert profiles.delete_profile(saved["id"]) is True
        assert profiles.find_by_fingerprint("csv", "fp_del") is None
