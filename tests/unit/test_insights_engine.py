"""Unit tests for the new InsightsEngine with tasking.
"""
import pytest
from unittest.mock import patch, MagicMock, ANY
from src.rag.insights_engine import InsightsEngine

@pytest.fixture
def engine():
    return InsightsEngine()

def test_empty_response_on_no_docs(engine):
    with patch("src.rag.insights_engine.get_retriever") as mock_ret:
        mock_ret.return_value.get_sample.return_value = []
        resp = engine.get_insights("ds")
        assert resp["tasks"] == {}
        assert resp["_meta"]["reason"] == "No documents"

def test_trigger_tasks_initially(engine):
    sample = [{"id": "1", "text": "doc1"}]
    with patch("src.rag.insights_engine.get_retriever") as mock_ret:
        mock_ret.return_value.get_sample.return_value = sample
        with patch.object(engine, "_load_all_from_cache", return_value={}):
            with patch.object(engine, "_trigger_tasks") as mock_trigger:
                engine.get_insights("ds")
                mock_trigger.assert_called_once()

def test_json_parsing_robustness(engine):
    raw = "Some text before ```json\n{\"key\": \"val\"}\n``` after"
    parsed = engine._parse_json(raw)
    assert parsed == {"key": "val"}

def test_stats_task_payload(engine):
    with patch("src.rag.insights_engine.get_retriever") as mock_ret:
        mock_ret.return_value.get_status.return_value = {"doc_count": 100}
        with patch.object(engine, "_set_task_status") as mock_status:
            engine._run_stats_task("ds", "hash")
            # Verify it eventually sets status to 'complete'
            mock_status.assert_any_call("ds", "stats", "complete", "hash", payload=ANY)

def test_ai_task_calls_llm(engine):
    sample = [{"id": "1", "text": "doc1"}]
    with patch("src.rag.insights_engine.get_llm") as mock_llm:
        mock_llm.return_value.complete_json.return_value = "{\"entities\": []}"
        with patch.object(engine, "_set_task_status") as mock_status:
            engine._run_ai_task("ds", "ner", sample, "hash")
            mock_llm.return_value.complete_json.assert_called_once()
            mock_status.assert_any_call("ds", "ner", "complete", "hash", payload={"entities": []})
