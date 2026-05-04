"""Unit tests for FileLoader datasource.

Uses temporary files — no external dependencies.
"""
import json
import csv
import uuid
import pytest
from pathlib import Path
from src.retrieval.file_loader import FileLoader


@pytest.fixture
def tmp_jsonl(tmp_path):
    """Create a temp JSONL corpus file."""
    p = tmp_path / "corpus.jsonl"
    docs = [
        {"id": str(uuid.uuid4()), "text": f"APT28 conducts phishing in {i} regions.", "source": "test"}
        for i in range(20)
    ]
    p.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
    return str(p)


@pytest.fixture
def tmp_csv(tmp_path):
    p = tmp_path / "corpus.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "text"])
        w.writeheader()
        for i in range(10):
            w.writerow({"id": f"d{i}", "text": f"DDoS campaign against sector {i}."})
    return str(p)


@pytest.fixture
def tmp_txt(tmp_path):
    p = tmp_path / "corpus.txt"
    paragraphs = [f"Paragraph {i}: Intelligence about topic {i}." for i in range(8)]
    p.write_text("\n\n".join(paragraphs), encoding="utf-8")
    return str(p)


class TestFileLoaderLoad:

    def test_loads_jsonl(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        loader.load()
        assert len(loader._chunks) == 20

    def test_loads_csv(self, tmp_csv):
        loader = FileLoader(tmp_csv)
        loader.load()
        assert len(loader._chunks) == 10

    def test_loads_txt_by_paragraphs(self, tmp_txt):
        loader = FileLoader(tmp_txt)
        loader.load()
        assert len(loader._chunks) == 8

    def test_missing_file_returns_empty(self, tmp_path):
        loader = FileLoader(str(tmp_path / "nonexistent.jsonl"))
        loader.load()
        assert loader._chunks == []

    def test_chunk_has_required_fields(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        loader.load()
        for chunk in loader._chunks:
            assert "id" in chunk
            assert "text" in chunk
            assert "source" in chunk
            assert "metadata" in chunk

    def test_load_is_idempotent(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        loader.load()
        loader.load()   # second call should be a no-op
        assert len(loader._chunks) == 20


class TestFileLoaderSearch:

    def test_returns_top_k_results(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        results = loader.search("APT28 phishing", top_k=3)
        assert len(results) <= 3

    def test_results_have_score(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        results = loader.search("APT28", top_k=5)
        assert all("score" in r for r in results)

    def test_irrelevant_query_may_return_empty(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        results = loader.search("xyzabc quantum spaghetti", top_k=5)
        # All BM25 scores may be 0 → filtered out
        for r in results:
            assert r["score"] > 0

    def test_search_triggers_load(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        # Don't call load() explicitly
        results = loader.search("phishing", top_k=3)
        assert loader._loaded is True

    def test_empty_corpus_returns_empty(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        loader = FileLoader(str(p))
        results = loader.search("anything", top_k=5)
        assert results == []


class TestFileLoaderGetSample:

    def test_returns_n_chunks(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        sample = loader.get_sample(10)
        assert len(sample) == 10

    def test_caps_at_corpus_size(self, tmp_jsonl):
        loader = FileLoader(tmp_jsonl)
        sample = loader.get_sample(1000)
        assert len(sample) == 20
