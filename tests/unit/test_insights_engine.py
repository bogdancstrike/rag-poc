"""Unit tests for the new InsightsEngine with tasking.
"""
import pytest
from unittest.mock import patch, MagicMock, ANY
from src.rag.insights_engine import InsightsEngine

@pytest.fixture
def engine():
    return InsightsEngine()

def test_empty_response_on_no_docs(engine):
    """get_insights() should return immediately with pending state; the coordinator
    runs in background and handles the no-docs case asynchronously.
    """
    with patch.object(engine, "_load_all_from_cache", return_value={}):
        with patch.object(engine, "_set_task_status") as mock_status:
            with patch("src.rag.insights_engine._executor") as mock_exec:
                resp = engine.get_insights("ds")
                # The HTTP response should come back immediately with pending tasks
                assert resp["_meta"]["refresh_triggered"] is True
                # Coordinator must be submitted to the executor
                mock_exec.submit.assert_called_once()

def test_trigger_tasks_initially(engine):
    """When no cache exists, get_insights() should mark tasks pending and submit coordinator."""
    with patch.object(engine, "_load_all_from_cache", return_value={}):
        with patch.object(engine, "_set_task_status"):
            with patch("src.rag.insights_engine._executor") as mock_exec:
                resp = engine.get_insights("ds")
                assert resp["_meta"]["refresh_triggered"] is True
                # Coordinator submitted as background job
                mock_exec.submit.assert_called_once_with(engine._run_coordinator, "ds")

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
