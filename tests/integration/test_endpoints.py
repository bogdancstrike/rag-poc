"""Integration tests for the Flask API endpoints.

Uses Flask test client with an in-memory SQLite DB and mocked ES/LLM.
No real Kafka, Elasticsearch, or Ollama required.
"""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ["DATABASE_URL"] = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def app():
    """Spin up the QF Framework Flask app in test mode."""
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "src"))

    from src.core.db import init_db
    init_db()

    from src.config import Config
    Config.DATASOURCE_TYPE = "file"
    Config.FILE_DATASOURCE_PATH = "/nonexistent.jsonl"

    from framework.app import FrameworkApp, FrameworkSettings
    settings = FrameworkSettings(
        enable_etl=False,
        enable_api=True,
        enable_dynamic_endpoints=True,
        api_host="0.0.0.0",
        api_port=5199,
        api_title="Test RAG API",
        endpoint_json_path="maps/endpoint.json",
        enable_tracing=False,
    )
    fw = FrameworkApp(settings)
    flask_app = fw.run().app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post(client, url, body):
    return client.post(url, data=json.dumps(body), content_type="application/json")


def _get(client, url, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"{url}?{qs}" if qs else url)


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:

    def test_liveness(self, client):
        r = client.get("/rag/liveness")
        assert r.status_code == 200
        assert json.loads(r.data)["alive"] is True

    def test_health_returns_status_and_datasource(self, client):
        r = client.get("/rag/health")
        assert r.status_code in (200, 503)
        data = json.loads(r.data)
        assert "status" in data
        assert "datasource" in data

    def test_health_includes_llm_field(self, client):
        r = client.get("/rag/health")
        data = json.loads(r.data)
        assert "llm" in data


# ── Sessions ──────────────────────────────────────────────────────────────────

class TestSessions:

    def test_create_with_defaults(self, client):
        r = _post(client, "/rag/v1/sessions", {})
        assert r.status_code == 201
        data = json.loads(r.data)
        assert "id" in data
        assert data["datasource"] == "default"

    def test_create_with_datasource(self, client):
        r = _post(client, "/rag/v1/sessions", {"datasource": "my_index"})
        assert r.status_code == 201
        assert json.loads(r.data)["datasource"] == "my_index"

    def test_create_with_title(self, client):
        r = _post(client, "/rag/v1/sessions", {"title": "My session"})
        assert json.loads(r.data)["title"] == "My session"

    def test_list_returns_sessions(self, client):
        _post(client, "/rag/v1/sessions", {})
        r = client.get("/rag/v1/sessions")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_get_returns_correct_session(self, client):
        sid = json.loads(_post(client, "/rag/v1/sessions", {"title": "t"}).data)["id"]
        r = client.get(f"/rag/v1/sessions/{sid}")
        assert r.status_code == 200
        assert json.loads(r.data)["id"] == sid

    def test_get_missing_returns_404(self, client):
        r = client.get("/rag/v1/sessions/nonexistent-id")
        assert r.status_code == 404

    def test_delete_removes_session(self, client):
        sid = json.loads(_post(client, "/rag/v1/sessions", {}).data)["id"]
        assert client.delete(f"/rag/v1/sessions/{sid}").status_code == 200
        assert client.get(f"/rag/v1/sessions/{sid}").status_code == 404

    def test_delete_missing_returns_404(self, client):
        r = client.delete("/rag/v1/sessions/no-such-session")
        assert r.status_code == 404

    def test_rename_session(self, client):
        sid = json.loads(_post(client, "/rag/v1/sessions", {}).data)["id"]
        r = _post(client, f"/rag/v1/sessions/{sid}", {"title": "New Name"})
        # PATCH or POST depending on framework
        if r.status_code == 405:
            r = client.patch(
                f"/rag/v1/sessions/{sid}",
                data=json.dumps({"title": "New Name"}),
                content_type="application/json",
            )
        assert r.status_code == 200
        assert json.loads(r.data)["title"] == "New Name"

    def test_messages_empty_for_new_session(self, client):
        sid = json.loads(_post(client, "/rag/v1/sessions", {}).data)["id"]
        r = client.get(f"/rag/v1/sessions/{sid}/messages")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["messages"] == []
        assert data["total"] == 0

    def test_list_filters_by_datasource(self, client):
        _post(client, "/rag/v1/sessions", {"datasource": "target_ds"})
        _post(client, "/rag/v1/sessions", {"datasource": "other_ds"})
        r = client.get("/rag/v1/sessions?datasource=target_ds")
        sessions = json.loads(r.data)["sessions"]
        assert all(s["datasource"] == "target_ds" for s in sessions)


# ── Chat ──────────────────────────────────────────────────────────────────────

class TestChat:

    def test_missing_message_returns_400(self, client):
        r = _post(client, "/rag/v1/chat", {})
        assert r.status_code == 400

    def test_chat_response_shape(self, client):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Mocked intelligence response."
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            {"id": "d1", "text": "Chunk text", "score": 0.9, "source": "file", "metadata": {}}
        ]
        with patch("api.endpoints.get_llm", return_value=mock_llm):
            with patch("api.endpoints.get_retriever", return_value=mock_retriever):
                r = _post(client, "/rag/v1/chat", {"message": "Who are top threat actors?"})
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "content"    in data
        assert "sources"    in data
        assert "session_id" in data
        assert data["content"] == "Mocked intelligence response."

    def test_chat_auto_creates_session(self, client):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Answer."
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        with patch("api.endpoints.get_llm", return_value=mock_llm):
            with patch("api.endpoints.get_retriever", return_value=mock_retriever):
                r = _post(client, "/rag/v1/chat", {"message": "Question?"})
        assert r.status_code == 200
        assert json.loads(r.data)["session_id"]

    def test_chat_with_existing_session(self, client):
        sid = json.loads(_post(client, "/rag/v1/sessions", {}).data)["id"]
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Contextual answer."
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        with patch("api.endpoints.get_llm", return_value=mock_llm):
            with patch("api.endpoints.get_retriever", return_value=mock_retriever):
                r = _post(client, "/rag/v1/chat", {"session_id": sid, "message": "Q?"})
        assert r.status_code == 200
        assert json.loads(r.data)["session_id"] == sid

    def test_chat_returns_sources_list(self, client):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Answer with sources."
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            {"id": "s1", "text": "Source text", "score": 0.85, "source": "es", "metadata": {}}
        ]
        with patch("api.endpoints.get_llm", return_value=mock_llm):
            with patch("api.endpoints.get_retriever", return_value=mock_retriever):
                r = _post(client, "/rag/v1/chat", {"message": "Find sources."})
        sources = json.loads(r.data)["sources"]
        assert isinstance(sources, list)
        assert len(sources) > 0


# ── Datasource ────────────────────────────────────────────────────────────────

class TestDatasource:

    def test_status_returns_type(self, client):
        r = client.get("/rag/v1/datasource/status")
        assert r.status_code == 200
        assert "type" in json.loads(r.data)

    def test_indices_returns_list(self, client):
        r = client.get("/rag/v1/datasource/indices")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "indices" in data
        assert isinstance(data["indices"], list)


# ── Tasks list ────────────────────────────────────────────────────────────────

class TestTasksList:

    def test_tasks_list_returns_200(self, client):
        r = client.get("/rag/v1/tasks")
        assert r.status_code == 200

    def test_tasks_list_response_shape(self, client):
        r = client.get("/rag/v1/tasks")
        data = json.loads(r.data)
        assert "tasks"  in data
        assert "total"  in data
        assert "stats"  in data
        assert "page"   in data
        assert "size"   in data

    def test_tasks_list_stats_keys(self, client):
        r = client.get("/rag/v1/tasks")
        stats = json.loads(r.data)["stats"]
        for key in ("total", "pending", "processing", "complete", "error"):
            assert key in stats

    def test_tasks_list_status_filter_accepted(self, client):
        r = client.get("/rag/v1/tasks?status=complete")
        assert r.status_code == 200

    def test_tasks_list_category_filter_accepted(self, client):
        r = client.get("/rag/v1/tasks?category=insight")
        assert r.status_code == 200

    def test_tasks_list_pagination_params(self, client):
        r = client.get("/rag/v1/tasks?page=1&size=10")
        data = json.loads(r.data)
        assert data["page"] == 1
        assert data["size"] == 10

    def test_tasks_list_sort_param_accepted(self, client):
        r = client.get("/rag/v1/tasks?sort=updated_at:desc")
        assert r.status_code == 200

    def test_tasks_list_datasource_filter(self, client):
        r = client.get("/rag/v1/tasks?datasource=qsint_docs")
        assert r.status_code == 200


# ── Tasks analytics ───────────────────────────────────────────────────────────

class TestTasksAnalytics:

    def test_analytics_returns_200(self, client):
        r = client.get("/rag/v1/tasks/analytics")
        assert r.status_code == 200

    def test_analytics_response_shape(self, client):
        r = client.get("/rag/v1/tasks/analytics")
        data = json.loads(r.data)
        assert "timing"      in data
        assert "throughput"  in data
        assert "status_dist" in data
        assert "type_dist"   in data
        assert "time_series" in data
        assert "total_tasks" in data

    def test_analytics_throughput_has_all_windows(self, client):
        r = client.get("/rag/v1/tasks/analytics")
        throughput = json.loads(r.data)["throughput"]
        for w in ("5m", "1h", "12h", "1d", "7d"):
            assert w in throughput
            assert isinstance(throughput[w], int)

    def test_analytics_timing_is_list(self, client):
        r = client.get("/rag/v1/tasks/analytics")
        assert isinstance(json.loads(r.data)["timing"], list)

    def test_analytics_time_series_is_list(self, client):
        r = client.get("/rag/v1/tasks/analytics")
        assert isinstance(json.loads(r.data)["time_series"], list)

    def test_analytics_datasource_filter_accepted(self, client):
        r = client.get("/rag/v1/tasks/analytics?datasource=qsint_docs")
        assert r.status_code == 200

    def test_analytics_category_filter_accepted(self, client):
        r = client.get("/rag/v1/tasks/analytics?category=insight")
        assert r.status_code == 200

    def test_analytics_total_tasks_is_int(self, client):
        r = client.get("/rag/v1/tasks/analytics")
        assert isinstance(json.loads(r.data)["total_tasks"], int)


# ── Task detail ───────────────────────────────────────────────────────────────

class TestTaskDetail:

    def test_missing_task_returns_404(self, client):
        r = client.get("/rag/v1/tasks/insight__nonexistent__summary")
        assert r.status_code == 404

    def test_malformed_task_id_returns_error(self, client):
        r = client.get("/rag/v1/tasks/badformat")
        assert r.status_code in (400, 404, 500)

    def test_enrichment_category_in_id_parsed(self, client):
        r = client.get("/rag/v1/tasks/enrichment__qsint_docs__doc-that-does-not-exist")
        assert r.status_code == 404


# ── Document enrichment ───────────────────────────────────────────────────────

class TestDocumentEnrichment:

    def test_enrich_missing_datasource_returns_400(self, client):
        r = _post(client, "/rag/v1/documents/enrich", {"doc_id": "d1", "text": "text"})
        assert r.status_code == 400

    def test_enrich_missing_text_returns_400(self, client):
        r = _post(client, "/rag/v1/documents/enrich", {"datasource": "ds", "doc_id": "d1"})
        assert r.status_code == 400

    def test_enrich_queues_task(self, client):
        with patch("src.tasking.producer.publish_task") as mock_pub:
            r = _post(client, "/rag/v1/documents/enrich", {
                "datasource": "ds", "doc_id": "d1", "text": "Threat intel text."
            })
        # Should be 200 (cached) or 202 (queued)
        assert r.status_code in (200, 202)

    def test_enrich_field_missing_field_returns_400(self, client):
        r = _post(client, "/rag/v1/documents/enrich/field", {
            "datasource": "ds", "doc_id": "d1", "text": "text"
        })
        assert r.status_code == 400
