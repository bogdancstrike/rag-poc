"""Unit tests for the RawRecord → ES doc normalizer."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from src.ingestion.handlers.base import RawRecord
from src.ingestion.normalizer import normalize, stable_doc_id


class TestStableDocId:

    def test_deterministic(self):
        a = stable_doc_id("file-1", 0)
        b = stable_doc_id("file-1", 0)
        assert a == b

    def test_distinct_per_record_index(self):
        a = stable_doc_id("file-1", 0)
        b = stable_doc_id("file-1", 1)
        assert a != b

    def test_distinct_per_file(self):
        a = stable_doc_id("file-1", 0)
        b = stable_doc_id("file-2", 0)
        assert a != b


class TestNormalize:

    def test_minimal_record_synthetic_title(self):
        """When no title is provided, the normalizer derives one from text
        so the UI table doesn't have blank cells."""
        rec = RawRecord(text="hello world")
        doc = normalize(rec, "file-x", "leak.csv")
        assert doc["text"] == "hello world"
        assert doc["source"] == "upload:leak.csv#0"
        assert doc["source_file"] == "file-x"
        # Synthetic title falls out of the first ~80 chars of text
        assert doc["title"] == "hello world"
        assert doc["title_synthetic"] is True

    def test_synthetic_title_when_text_is_empty(self):
        rec = RawRecord(text="", record_index=7)
        doc = normalize(rec, "file-x", "blank.csv")
        assert doc["title"] == "blank.csv #7"
        assert doc["title_synthetic"] is True

    def test_real_title_kept_and_flagged_non_synthetic(self):
        rec = RawRecord(text="x", title="Real title")
        doc = normalize(rec, "file-x", "f.csv")
        assert doc["title"] == "Real title"
        assert doc["title_synthetic"] is False

    def test_full_record(self):
        rec = RawRecord(
            text="payload",
            title="hello",
            author="@bogdan",
            created_at="2024-01-15T08:14:22Z",
            url="https://example.com",
            raw={"k": "v"},
            record_index=4,
        )
        doc = normalize(rec, "file-1", "social_posts.csv")
        assert doc["title"] == "hello"
        assert doc["author"] == "@bogdan"
        assert doc["url"] == "https://example.com"
        assert doc["raw"] == {"k": "v"}
        assert doc["source"].endswith("#4")
        assert doc["source_index"] == 4

    def test_text_truncation(self):
        # default INGEST_TEXT_TRUNCATE = 20000; produce a longer string
        big = "x" * 25000
        rec = RawRecord(text=big)
        doc = normalize(rec, "file-x", "big.txt")
        assert len(doc["text"]) <= 20000

    def test_raw_value_trimming(self):
        # raw values capped per-key at 4000 chars
        big_value = "x" * 5000
        rec = RawRecord(text="t", raw={"summary": big_value, "small": "ok"})
        doc = normalize(rec, "file-x", "f.csv")
        assert len(doc["raw"]["summary"]) == 4000
        assert doc["raw"]["small"] == "ok"
