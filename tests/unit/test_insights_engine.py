"""Unit tests for InsightsEngine — cache logic and JSON parsing.

LLM and DB calls are mocked.
"""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from src.rag.insights_engine import InsightsEngine


@pytest.fixture
def engine():
    return InsightsEngine()


VALID_PAYLOAD = {
    "hot_topics": [
        {"topic": "APT28 activity", "count_estimate": 150, "summary": "Rising", "sentiment": "negative"}
    ],
    "narratives": [
        {"title": "Disinformation surge", "description": "Coordinated", "evidence_docs": ["d1"]}
    ],
    "trends": [
        {"label": "Phishing", "direction": "rising", "change_pct": 23.5, "time_period": "30d"}
    ],
    "entities": [
        {"name": "APT28", "type": "org", "frequency": 45, "related": ["GRU"]}
    ],
    "anomalies": [
        {"description": "Unusual spike", "docs": ["d1", "d2"]}
    ],
}


class TestParseJson:

    def test_parses_clean_json(self, engine):
        raw = json.dumps(VALID_PAYLOAD)
        result = engine._parse_json(raw)
        assert result == VALID_PAYLOAD

    def test_strips_markdown_fences(self, engine):
        raw = f"```json\n{json.dumps(VALID_PAYLOAD)}\n```"
        result = engine._parse_json(raw)
        assert result is not None
        assert "hot_topics" in result

    def test_returns_none_for_invalid_json(self, engine):
        assert engine._parse_json("not json at all") is None

    def test_extracts_embedded_json(self, engine):
        raw = f"Some preamble text\n{json.dumps(VALID_PAYLOAD)}\nSome suffix"
        result = engine._parse_json(raw)
        assert result is not None

    def test_returns_none_for_empty_string(self, engine):
        assert engine._parse_json("") is None


class TestEmptyInsights:

    def test_returns_valid_structure(self, engine):
        result = engine._empty_insights("default", reason="test")
        assert "hot_topics" in result
        assert "narratives" in result
        assert "trends" in result
        assert "entities" in result
        assert "anomalies" in result
        assert result["_meta"]["reason"] == "test"

    def test_all_lists_are_empty(self, engine):
        result = engine._empty_insights("ds")
        for key in ("hot_topics", "narratives", "trends", "entities", "anomalies"):
            assert result[key] == []


class TestGetInsights:

    def test_returns_empty_when_no_docs(self, engine):
        with patch("src.rag.insights_engine.get_retriever") as mock_ret:
            mock_ret.return_value.get_sample.return_value = []
            with patch.object(engine, "_load_from_cache", return_value=None):
                result = engine.get_insights(datasource="empty_ds")
        assert result["hot_topics"] == []
        assert "reason" in result["_meta"]

    def test_returns_cached_when_fresh(self, engine):
        cached = {**VALID_PAYLOAD, "_meta": {"cached": True, "generated_at": "2026-01-01"}}
        with patch.object(engine, "_load_from_cache", return_value=cached):
            result = engine.get_insights(datasource="default")
        assert result["_meta"]["cached"] is True

    def test_generates_when_cache_empty(self, engine):
        with patch.object(engine, "_load_from_cache", return_value=None):
            with patch.object(engine, "_generate_and_cache", return_value={**VALID_PAYLOAD, "_meta": {}}) as mock_gen:
                engine.get_insights(datasource="default")
                mock_gen.assert_called_once()

    def test_force_refresh_skips_cache(self, engine):
        with patch.object(engine, "_generate_and_cache", return_value={**VALID_PAYLOAD, "_meta": {}}) as mock_gen:
            with patch.object(engine, "_load_from_cache", return_value=VALID_PAYLOAD):
                engine.get_insights(datasource="default", force_refresh=True)
                mock_gen.assert_called_once()
