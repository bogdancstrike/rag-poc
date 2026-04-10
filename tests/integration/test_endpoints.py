"""Integration tests for the Flask API endpoints.

Uses Flask test client — no real ES or LLM required (mocked).
Tests are run against a real in-memory SQLite DB.
"""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# We need to patch ES and LLM before main.py imports anything
with patch("src.datasource.es_client.ESClient"):
    pass


@pytest.fixture(scope="module")
def app():
    """Create the Flask app via main.py logic (QF Framework)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from src.session.models import init_db
    init_db()

    # Import the Flask app that QF creates
    # We do this by starting FrameworkApp in API-only mode
    from src.config import Config
    Config.DATASOURCE_TYPE = "file"
    Config.FILE_DATASOURCE_PATH = "/nonexistent.jsonl"  # triggers empty file loader

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
    handles = fw.run()
    flask_app = handles.app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthEndpoints:

    def test_liveness(self, client):
        r = client.get("/rag/liveness")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["alive"] is True

    def test_health_returns_status(self, client):
        r = client.get("/rag/health")
        assert r.status_code in (200, 503)
        data = json.loads(r.data)
        assert "status" in data
        assert "datasource" in data


class TestSessionEndpoints:

    def test_create_session(self, client):
        r = client.post(
            "/rag/v1/sessions",
            data=json.dumps({"datasource": "test_ds"}),
            content_type="application/json",
        )
        assert r.status_code == 201
        data = json.loads(r.data)
        assert "id" in data
        assert data["datasource"] == "test_ds"

    def test_list_sessions(self, client):
        client.post(
            "/rag/v1/sessions",
            data=json.dumps({}),
            content_type="application/json",
        )
        r = client.get("/rag/v1/sessions")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_get_session(self, client):
        r = client.post(
            "/rag/v1/sessions",
            data=json.dumps({"title": "My session"}),
            content_type="application/json",
        )
        sid = json.loads(r.data)["id"]

        r2 = client.get(f"/rag/v1/sessions/{sid}")
        assert r2.status_code == 200
        assert json.loads(r2.data)["id"] == sid

    def test_get_missing_session_returns_404(self, client):
        r = client.get("/rag/v1/sessions/nonexistent-id")
        assert r.status_code == 404

    def test_delete_session(self, client):
        r = client.post("/rag/v1/sessions", data=json.dumps({}), content_type="application/json")
        sid = json.loads(r.data)["id"]
        r2 = client.delete(f"/rag/v1/sessions/{sid}")
        assert r2.status_code == 200
        r3 = client.get(f"/rag/v1/sessions/{sid}")
        assert r3.status_code == 404

    def test_rename_session(self, client):
        r = client.post("/rag/v1/sessions", data=json.dumps({}), content_type="application/json")
        sid = json.loads(r.data)["id"]
        r2 = client.patch(
            f"/rag/v1/sessions/{sid}",
            data=json.dumps({"title": "New Name"}),
            content_type="application/json",
        )
        assert r2.status_code == 200
        assert json.loads(r2.data)["title"] == "New Name"

    def test_get_messages_empty(self, client):
        r = client.post("/rag/v1/sessions", data=json.dumps({}), content_type="application/json")
        sid = json.loads(r.data)["id"]
        r2 = client.get(f"/rag/v1/sessions/{sid}/messages")
        assert r2.status_code == 200
        data = json.loads(r2.data)
        assert data["messages"] == []
        assert data["total"] == 0


class TestChatEndpoint:

    def test_chat_requires_message_field(self, client):
        r = client.post(
            "/rag/v1/chat",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_chat_with_mock_llm(self, client):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Mocked LLM response."

        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            {"id": "d1", "text": "Test chunk", "score": 0.9, "source": "file", "metadata": {}}
        ]

        with patch("src.api.endpoints.get_llm", return_value=mock_llm):
            with patch("src.api.endpoints.get_retriever", return_value=mock_retriever):
                r = client.post(
                    "/rag/v1/chat",
                    data=json.dumps({"message": "Who are the top threat actors?"}),
                    content_type="application/json",
                )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "content" in data
        assert "sources" in data
        assert "session_id" in data
        assert data["content"] == "Mocked LLM response."

    def test_chat_creates_session_automatically(self, client):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Auto-session response."
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []

        with patch("src.api.endpoints.get_llm", return_value=mock_llm):
            with patch("src.api.endpoints.get_retriever", return_value=mock_retriever):
                r = client.post(
                    "/rag/v1/chat",
                    data=json.dumps({"message": "Test question"}),
                    content_type="application/json",
                )
        assert r.status_code == 200
        assert json.loads(r.data)["session_id"]


class TestDatasourceStatus:

    def test_returns_type_and_info(self, client):
        r = client.get("/rag/v1/datasource/status")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "type" in data
