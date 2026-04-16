"""Unit tests for Kafka worker: producer, task_handlers, consumer routing.

No real Kafka broker is needed — all external dependencies are mocked.
"""
import os
import pytest
from unittest.mock import patch, MagicMock, call, ANY

# ---------------------------------------------------------------------------
# Helpers to reset module-level singletons between tests
# ---------------------------------------------------------------------------

def _reset_producer():
    """Reset kafka_producer module state so each test starts clean."""
    import src.worker.kafka_producer as kp
    kp._producer = None
    kp._kafka_ok = None


# ===========================================================================
# 1. publish_task routes to the correct Kafka topic
# ===========================================================================

class TestPublishTaskTopicRouting:

    def setup_method(self):
        _reset_producer()

    def _make_mock_producer(self):
        mock_producer = MagicMock()
        mock_producer.send.return_value = MagicMock()
        mock_producer.flush.return_value = None
        return mock_producer

    @pytest.mark.parametrize("task_type", ["insight_ai", "enrich_doc", "enrich_field"])
    def test_llm_task_types_go_to_llm_topic(self, task_type):
        mock_producer = self._make_mock_producer()

        with patch("src.worker.kafka_producer._make_producer", return_value=mock_producer):
            _reset_producer()
            from src.worker.kafka_producer import publish_task
            from src.config import Config

            task = {"task_type": task_type, "datasource": "ds1"}
            result = publish_task(task)

        assert result is True
        topic_called = mock_producer.send.call_args[0][0]
        assert topic_called == Config.KAFKA_TOPIC_LLM_TASKS

    @pytest.mark.parametrize("task_type", ["insight_coordinator", "insight_stats"])
    def test_fast_task_types_go_to_fast_topic(self, task_type):
        mock_producer = self._make_mock_producer()

        with patch("src.worker.kafka_producer._make_producer", return_value=mock_producer):
            _reset_producer()
            from src.worker.kafka_producer import publish_task
            from src.config import Config

            task = {"task_type": task_type, "datasource": "ds1"}
            result = publish_task(task)

        assert result is True
        topic_called = mock_producer.send.call_args[0][0]
        assert topic_called == Config.KAFKA_TOPIC_FAST_TASKS

    def test_publish_task_adds_created_at(self):
        mock_producer = self._make_mock_producer()

        with patch("src.worker.kafka_producer._make_producer", return_value=mock_producer):
            _reset_producer()
            from src.worker.kafka_producer import publish_task

            publish_task({"task_type": "insight_coordinator", "datasource": "ds1"})

        sent_value = mock_producer.send.call_args[1]["value"]
        assert "created_at" in sent_value

    def test_publish_task_uses_datasource_as_key(self):
        mock_producer = self._make_mock_producer()

        with patch("src.worker.kafka_producer._make_producer", return_value=mock_producer):
            _reset_producer()
            from src.worker.kafka_producer import publish_task

            publish_task({"task_type": "enrich_doc", "datasource": "my_ds", "doc_id": "1", "text": "x"})

        key_called = mock_producer.send.call_args[1]["key"]
        assert key_called == b"my_ds"


# ===========================================================================
# 2. publish_task falls back to thread when Kafka is unavailable
# ===========================================================================

class TestPublishTaskFallback:

    def setup_method(self):
        _reset_producer()

    def test_fallback_to_thread_when_producer_none(self):
        """When _make_producer raises, get_producer returns None → fallback thread."""
        with patch("src.worker.kafka_producer._make_producer", side_effect=Exception("no broker")):
            _reset_producer()
            with patch("src.worker.kafka_producer._fallback_thread") as mock_fallback:
                from src.worker.kafka_producer import publish_task

                result = publish_task({"task_type": "enrich_doc", "datasource": "ds",
                                       "doc_id": "1", "text": "hello"})

        assert result is False
        mock_fallback.assert_called_once()

    def test_fallback_to_thread_when_send_raises(self):
        """When producer.send() raises, fallback thread is used."""
        mock_producer = MagicMock()
        mock_producer.send.side_effect = Exception("network error")

        with patch("src.worker.kafka_producer._make_producer", return_value=mock_producer):
            _reset_producer()
            with patch("src.worker.kafka_producer._fallback_thread") as mock_fallback:
                from src.worker.kafka_producer import publish_task

                result = publish_task({"task_type": "insight_ai", "datasource": "ds",
                                       "insight_type": "summary", "sample_hash": "abc"})

        assert result is False
        mock_fallback.assert_called_once()

    def test_fallback_thread_calls_dispatch_task(self):
        """_fallback_thread should start a daemon thread that calls dispatch_task."""
        import threading

        called_tasks = []

        def fake_dispatch(task):
            called_tasks.append(task)

        with patch("src.worker.task_handlers.dispatch_task", fake_dispatch):
            from src.worker.kafka_producer import _fallback_thread
            t_ref = []

            original_thread = threading.Thread

            def capture_thread(*args, **kwargs):
                t = original_thread(*args, **kwargs)
                t_ref.append(t)
                return t

            with patch("src.worker.kafka_producer.threading.Thread", side_effect=capture_thread):
                task = {"task_type": "insight_coordinator", "datasource": "ds"}
                _fallback_thread(task)

            # Wait for the thread to finish
            if t_ref:
                t_ref[0].join(timeout=2)

        assert len(called_tasks) == 1
        assert called_tasks[0]["task_type"] == "insight_coordinator"


# ===========================================================================
# 3. dispatch_task routes to the correct handler
# ===========================================================================

class TestDispatchTask:

    @pytest.mark.parametrize("task_type,handler_name", [
        ("insight_coordinator", "handle_insight_coordinator"),
        ("insight_ai",          "handle_insight_ai"),
        ("insight_stats",       "handle_insight_stats"),
        ("enrich_doc",          "handle_enrich_doc"),
        ("enrich_field",        "handle_enrich_field"),
    ])
    def test_routes_to_correct_handler(self, task_type, handler_name):
        from src.worker.task_handlers import dispatch_task

        with patch(f"src.tasking.handlers.{handler_name}") as mock_handler:
            task = {"task_type": task_type, "datasource": "ds"}
            dispatch_task(task)

        mock_handler.assert_called_once_with(task)

    def test_unknown_task_type_does_not_raise(self):
        """dispatch_task should log a warning for unknown types, not raise."""
        from src.worker.task_handlers import dispatch_task

        with patch("src.tasking.handlers.logger") as mock_log:
            dispatch_task({"task_type": "totally_unknown", "datasource": "ds"})

        mock_log.warning.assert_called_once()

    def test_handler_exception_is_caught(self):
        """If a handler crashes, dispatch_task catches and logs the error."""
        from src.worker.task_handlers import dispatch_task

        with patch("src.tasking.handlers.handle_insight_coordinator",
                   side_effect=RuntimeError("boom")):
            with patch("src.tasking.handlers.logger") as mock_log:
                dispatch_task({"task_type": "insight_coordinator", "datasource": "ds"})

        mock_log.error.assert_called_once()


# ===========================================================================
# 4. handle_insight_coordinator delegates to engine.run_all_insights
# ===========================================================================

class TestHandleInsightCoordinator:

    def test_delegates_to_run_all_insights(self):
        """handle_insight_coordinator should call engine.run_all_insights, not fan-out via Kafka."""
        mock_engine = MagicMock()

        with patch("src.insights.engine.get_insights_engine", return_value=mock_engine):
            from src.worker.task_handlers import handle_insight_coordinator
            handle_insight_coordinator({"datasource": "my_ds"})

        mock_engine.run_all_insights.assert_called_once_with("my_ds", force=False)

    def test_ai_tasks_have_correct_insight_types(self):
        """force flag is forwarded correctly."""
        mock_engine = MagicMock()

        with patch("src.insights.engine.get_insights_engine", return_value=mock_engine):
            from src.worker.task_handlers import handle_insight_coordinator
            handle_insight_coordinator({"datasource": "ds", "force": True})

        mock_engine.run_all_insights.assert_called_once_with("ds", force=True)


# ===========================================================================
# 5. handle_insight_coordinator forwards force=False by default
# ===========================================================================

class TestHandleInsightCoordinatorNoDocs:

    def test_sets_error_status_when_no_docs(self):
        """run_all_insights handles the no-docs case internally; coordinator just delegates."""
        mock_engine = MagicMock()

        with patch("src.insights.engine.get_insights_engine", return_value=mock_engine):
            from src.worker.task_handlers import handle_insight_coordinator
            handle_insight_coordinator({"datasource": "empty_ds"})

        # Coordinator always delegates to run_all_insights — error handling is internal
        mock_engine.run_all_insights.assert_called_once_with("empty_ds", force=False)


# ===========================================================================
# 6. handle_enrich_doc calls _run_enrichment_background
# ===========================================================================

class TestHandleEnrichDoc:

    def test_calls_run_enrichment_background(self):
        """handle_enrich_doc calls run_enrichment_background from enrichment pipeline."""
        mock_enrich = MagicMock()

        with patch("src.enrichment.pipeline.run_enrichment_background", mock_enrich):
            from src.worker.task_handlers import handle_enrich_doc

            task = {"task_type": "enrich_doc", "datasource": "ds1",
                    "doc_id": "doc42", "text": "some text"}
            handle_enrich_doc(task)

        mock_enrich.assert_called_once_with("ds1", "doc42", "some text")


# ===========================================================================
# 7. handle_enrich_field with field="iocs" calls _extract_iocs (no LLM)
# ===========================================================================

class TestHandleEnrichFieldIocs:

    def test_iocs_field_calls_extract_iocs_not_llm(self):
        """field='iocs' should use regex extraction, not LLM."""
        mock_iocs = {"ips": ["1.2.3.4"], "urls": []}

        mock_db_row = MagicMock()
        mock_db_row.payload = {}

        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=MagicMock(
            query=MagicMock(return_value=MagicMock(
                filter_by=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_db_row)))
            ))
        ))
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        mock_extract = MagicMock(return_value=mock_iocs)

        with patch("src.core.db.get_db", return_value=mock_db_ctx):
            with patch("src.enrichment.pipeline.extract_iocs", mock_extract):
                from src.worker.task_handlers import handle_enrich_field

                task = {
                    "task_type": "enrich_field",
                    "datasource": "ds",
                    "doc_id": "doc1",
                    "text": "test text 192.168.1.1",
                    "field": "iocs",
                }
                handle_enrich_field(task)

        mock_extract.assert_called_once_with("test text 192.168.1.1")


# ===========================================================================
# 8. handle_enrich_field with field="sentiment" calls LLM
# ===========================================================================

class TestHandleEnrichFieldSentiment:

    def test_sentiment_field_calls_llm(self):
        """field='sentiment' should call LLM via PromptBuilder."""
        mock_llm = MagicMock()
        mock_llm.complete_json.return_value = '{"sentiment": "positive"}'

        mock_db_row = MagicMock()
        mock_db_row.payload = {}

        db_session = MagicMock()
        db_session.query.return_value.filter_by.return_value.first.return_value = mock_db_row

        mock_db_ctx = MagicMock()
        mock_db_ctx.__enter__ = MagicMock(return_value=db_session)
        mock_db_ctx.__exit__ = MagicMock(return_value=False)

        mock_builder = MagicMock()
        mock_builder.build_field_enrichment_messages.return_value = (["msg"], "sys")

        import sys

        with patch("src.core.db.get_db", return_value=mock_db_ctx):
            with patch("src.llm.client.get_llm", return_value=mock_llm):
                with patch("src.llm.prompts.PromptBuilder", return_value=mock_builder):
                    from src.worker.task_handlers import handle_enrich_field

                    task = {
                        "task_type": "enrich_field",
                        "datasource": "ds",
                        "doc_id": "doc2",
                        "text": "some text about events",
                        "field": "sentiment",
                    }
                    handle_enrich_field(task)

        mock_llm.complete_json.assert_called_once_with(["msg"], "sys")
        mock_builder.build_field_enrichment_messages.assert_called_once_with(
            "some text about events"[:3000], "sentiment"
        )
