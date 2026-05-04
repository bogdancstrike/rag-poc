"""Unit tests for InsightsEngine — task orchestration, JSON parsing, empty-result handling."""
import pytest
from unittest.mock import patch, MagicMock, ANY
from src.insights.engine import InsightsEngine


@pytest.fixture
def engine():
    return InsightsEngine()


# ── get_insights() — HTTP-facing, must be non-blocking ──────────────────────

class TestGetInsights:

    def test_returns_immediately_with_pending_state(self, engine):
        with patch.object(engine, "_load_all_from_cache", return_value={}):
            with patch.object(engine, "_set_task_status"):
                with patch("src.core.db.get_db"):
                    with patch("src.tasking.producer.publish_task"):
                        resp = engine.get_insights("ds")
        assert resp["_meta"]["refresh_triggered"] is True

    def test_publishes_coordinator_task(self, engine):
        with patch.object(engine, "_load_all_from_cache", return_value={}):
            with patch.object(engine, "_set_task_status"):
                with patch("src.core.db.get_db"):
                    with patch("src.tasking.producer.publish_task") as mock_pub:
                        engine.get_insights("ds")
        mock_pub.assert_called_once_with(
            {"task_type": "insight_coordinator", "datasource": "ds", "force": False}
        )

    def test_does_not_refresh_when_recently_updated(self, engine):
        """If all tasks completed recently, no refresh should be triggered."""
        from datetime import datetime, timezone, timedelta
        recent = datetime.now(timezone.utc) - timedelta(minutes=2)
        # All 8 tasks must be recently completed
        cache = {
            "trending_signals":      {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
            "active_narratives":     {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
            "hot_topics_sentiment":  {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
            "relationship_network":  {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
            "corpus_statistics":     {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
            "top_regions":           {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
            "top_entities":          {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
            "top_platforms":         {"status": "complete", "generated_at": recent.isoformat(), "updated_at": recent.isoformat()},
        }
        with patch.object(engine, "_load_all_from_cache", return_value=cache):
            with patch("src.tasking.producer.publish_task") as mock_pub:
                resp = engine.get_insights("ds")
        mock_pub.assert_not_called()
        assert resp["_meta"]["refresh_triggered"] is False

    def test_stale_cache_triggers_refresh(self, engine):
        """Tasks older than 10 minutes should trigger a refresh."""
        from datetime import datetime, timezone, timedelta
        old = datetime.now(timezone.utc) - timedelta(minutes=15)
        cache = {
            "hot_topics_sentiment": {"status": "complete", "updated_at": old},
        }
        with patch.object(engine, "_load_all_from_cache", return_value=cache):
            with patch.object(engine, "_set_task_status"):
                with patch("src.core.db.get_db"):
                    with patch("src.tasking.producer.publish_task") as mock_pub:
                        resp = engine.get_insights("ds")
        mock_pub.assert_called_once()
        assert resp["_meta"]["refresh_triggered"] is True


# ── _parse_json() — robustness across LLM output formats ────────────────────

class TestParseJson:

    def test_plain_json_object(self, engine):
        assert engine._parse_json('{"key": "value"}') == {"key": "value"}

    def test_markdown_fenced_json(self, engine):
        raw = "Some text before ```json\n{\"key\": \"val\"}\n``` after"
        assert engine._parse_json(raw) == {"key": "val"}

    def test_trailing_comma_fixed(self, engine):
        raw = '{"items": [1, 2, 3,]}'
        result = engine._parse_json(raw)
        assert result is not None
        assert "items" in result

    def test_returns_none_on_garbage(self, engine):
        assert engine._parse_json("not json at all!!!") is None

    def test_returns_none_on_empty_string(self, engine):
        assert engine._parse_json("") is None

    def test_empty_dict_returns_empty_dict_not_none(self, engine):
        """An empty {} from the LLM should parse to {} (falsy but not None)."""
        result = engine._parse_json("{}")
        assert result is not None   # distinguishes from parse failure
        assert result == {}

    def test_nested_json_parsed(self, engine):
        raw = '{"nodes": [{"id": "a"}], "edges": []}'
        result = engine._parse_json(raw)
        assert result["nodes"][0]["id"] == "a"
        assert result["edges"] == []

    def test_json_with_leading_think_block(self, engine):
        """Qwen3 may prefix output with <think>...</think> blocks."""
        raw = "<think>I need to think about this.</think>\n{\"summary\": \"hello\"}"
        result = engine._parse_json(raw)
        assert result == {"summary": "hello"}


# ── Empty {} from LLM → complete (not error) ────────────────────────────────

class TestEmptyJsonHandling:

    def test_empty_json_does_not_raise(self, engine):
        """`{}` from LLM should be stored as complete with empty payload, not an error."""
        sample = [{"id": "1", "text": "doc1"}]
        with patch("src.insights.engine.get_llm") as mock_llm:
            mock_llm.return_value.complete_json.return_value = "{}"
            with patch.object(engine, "_set_task_status") as mock_status:
                with patch("src.core.db.get_db"):
                    engine._run_ai_task("ds", "relationship_network", sample, "hash")

        calls = [c for c in mock_status.call_args_list if c[0][2] == "complete"]
        assert len(calls) == 1
        assert (calls[0][1].get("payload") == {} or calls[0][0][4] == {})

    def test_empty_json_does_not_set_error_status(self, engine):
        sample = [{"id": "1", "text": "doc1"}]
        with patch("src.insights.engine.get_llm") as mock_llm:
            mock_llm.return_value.complete_json.return_value = "{}"
            with patch.object(engine, "_set_task_status") as mock_status:
                with patch("src.core.db.get_db"):
                    engine._run_ai_task("ds", "hot_topics_sentiment", sample, "hash")

        error_calls = [c for c in mock_status.call_args_list if c[0][2] == "error"]
        assert len(error_calls) == 0

    def test_unparseable_json_sets_error_status(self, engine):
        """Completely unparseable output (None from _parse_json) → error status."""
        sample = [{"id": "1", "text": "doc1"}]
        with patch("src.insights.engine.get_llm") as mock_llm:
            mock_llm.return_value.complete_json.return_value = "totally unparseable garbage !!!"
            with patch.object(engine, "_set_task_status") as mock_status:
                with patch("src.core.db.get_db"):
                    engine._run_ai_task("ds", "relationship_network", sample, "hash")

        error_calls = [c for c in mock_status.call_args_list if c[0][2] == "error"]
        assert len(error_calls) == 1


# ── _run_stats_task() ────────────────────────────────────────────────────────

class TestRunStatsTask:

    def test_sets_complete_status_with_payload(self, engine):
        with patch("src.insights.engine.get_retriever") as mock_ret:
            mock_ret.return_value.get_status.return_value = {"doc_count": 100}
            mock_ret.return_value.get_aggregations.return_value = {}
            with patch.object(engine, "_set_task_status") as mock_status:
                with patch("src.core.db.get_db"):
                    engine._run_stats_task("ds", "corpus_statistics", "hash")

        complete_calls = [c for c in mock_status.call_args_list if c[0][2] == "complete"]
        assert len(complete_calls) == 1

    def test_stats_payload_is_dict(self, engine):
        with patch("src.insights.engine.get_retriever") as mock_ret:
            mock_ret.return_value.get_status.return_value = {"doc_count": 50}
            mock_ret.return_value.get_aggregations.return_value = {}
            with patch.object(engine, "_set_task_status") as mock_status:
                with patch("src.core.db.get_db"):
                    engine._run_stats_task("ds", "corpus_statistics", "hash")

        complete_call = next(c for c in mock_status.call_args_list if c[0][2] == "complete")
        payload = complete_call[1].get("payload", complete_call[0][4] if len(complete_call[0]) > 4 else None)
        assert isinstance(payload, dict)


# ── _run_ai_task() ───────────────────────────────────────────────────────────

class TestRunAiTask:

    def test_calls_llm_complete_json(self, engine):
        sample = [{"id": "1", "text": "doc1"}]
        with patch("src.insights.engine.get_llm") as mock_llm:
            mock_llm.return_value.complete_json.return_value = '{"hot_topics": []}'
            with patch.object(engine, "_set_task_status"):
                with patch("src.core.db.get_db"):
                    engine._run_ai_task("ds", "hot_topics_sentiment", sample, "hash")
        mock_llm.return_value.complete_json.assert_called_once()

    def test_complete_status_on_success(self, engine):
        sample = [{"id": "1", "text": "doc1"}]
        with patch("src.insights.engine.get_llm") as mock_llm:
            mock_llm.return_value.complete_json.return_value = '{"hot_topics": []}'
            with patch.object(engine, "_set_task_status") as mock_status:
                with patch("src.core.db.get_db"):
                    engine._run_ai_task("ds", "hot_topics_sentiment", sample, "hash")

        complete_calls = [c for c in mock_status.call_args_list if c[0][2] == "complete"]
        assert len(complete_calls) == 1

    def test_error_status_on_llm_exception(self, engine):
        sample = [{"id": "1", "text": "doc1"}]
        with patch("src.insights.engine.get_llm") as mock_llm:
            mock_llm.return_value.complete_json.side_effect = RuntimeError("LLM crashed")
            with patch.object(engine, "_set_task_status") as mock_status:
                with patch("src.core.db.get_db"):
                    engine._run_ai_task("ds", "active_narratives", sample, "hash")

        error_calls = [c for c in mock_status.call_args_list if c[0][2] == "error"]
        assert len(error_calls) == 1


# ── InsightsEventBus ─────────────────────────────────────────────────────────

class TestInsightsEventBus:

    def test_subscribe_returns_queue(self):
        from src.insights.engine import InsightsEventBus
        bus = InsightsEventBus()
        q = bus.subscribe("ds1")
        import queue
        assert isinstance(q, queue.Queue)

    def test_publish_delivers_to_subscriber(self):
        from src.insights.engine import InsightsEventBus
        bus = InsightsEventBus()
        q = bus.subscribe("ds1")
        bus.publish("ds1", {"type": "test", "status": "complete"})
        event = q.get_nowait()
        assert event["type"] == "test"

    def test_unsubscribe_stops_delivery(self):
        from src.insights.engine import InsightsEventBus
        import queue as q_mod
        bus = InsightsEventBus()
        q = bus.subscribe("ds1")
        bus.unsubscribe("ds1", q)
        bus.publish("ds1", {"type": "test"})
        with pytest.raises(q_mod.Empty):
            q.get_nowait()

    def test_multiple_subscribers_all_receive(self):
        from src.insights.engine import InsightsEventBus
        bus = InsightsEventBus()
        q1 = bus.subscribe("ds1")
        q2 = bus.subscribe("ds1")
        bus.publish("ds1", {"type": "done"})
        assert q1.get_nowait()["type"] == "done"
        assert q2.get_nowait()["type"] == "done"

    def test_publish_to_wrong_datasource_not_delivered(self):
        from src.insights.engine import InsightsEventBus
        import queue as q_mod
        bus = InsightsEventBus()
        q = bus.subscribe("ds1")
        bus.publish("ds2", {"type": "test"})
        with pytest.raises(q_mod.Empty):
            q.get_nowait()
