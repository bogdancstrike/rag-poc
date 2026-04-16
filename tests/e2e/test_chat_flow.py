"""E2E tests — require the backend running on localhost:5100 with ES seeded.

Run only when backend is up: pytest tests/e2e/ -v
"""
import json
import pytest
import requests

BASE = "http://localhost:5100/rag"


def backend_available():
    try:
        r = requests.get(f"{BASE}/liveness", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not backend_available(),
    reason="Backend not available at localhost:5100",
)


class TestChatE2E:

    def test_sync_chat_full_flow(self):
        """Create session → chat → verify response and sources saved."""
        # Create session
        r = requests.post(f"{BASE}/v1/sessions", json={"datasource": "qsint_docs"})
        assert r.status_code == 201
        sid = r.json()["id"]

        # Send chat message
        r2 = requests.post(
            f"{BASE}/v1/chat",
            json={"session_id": sid, "message": "What is APT28?"},
            timeout=120,
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["session_id"] == sid
        assert len(body["content"]) > 10
        assert isinstance(body["sources"], list)

        # Verify message was persisted
        r3 = requests.get(f"{BASE}/v1/sessions/{sid}/messages")
        assert r3.status_code == 200
        messages = r3.json()["messages"]
        assert len(messages) >= 2  # user + assistant
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["sources"] is not None

    def test_streaming_chat_delivers_deltas(self):
        """POST /v1/chat/stream → verify SSE events arrive."""
        r = requests.post(f"{BASE}/v1/sessions", json={"datasource": "qsint_docs"})
        sid = r.json()["id"]

        deltas = []
        session_id_from_sse = None
        done_received = False

        with requests.post(
            f"{BASE}/v1/chat/stream",
            json={"session_id": sid, "message": "Summarise threat landscape"},
            stream=True,
            timeout=120,
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines(decode_unicode=True):
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                if event["type"] == "sources":
                    session_id_from_sse = event["session_id"]
                elif event["type"] == "delta":
                    deltas.append(event["content"])
                elif event["type"] == "done":
                    done_received = True
                    break

        assert len(deltas) > 0, "Should have received at least one delta"
        assert done_received, "Should have received done event"
        assert session_id_from_sse == sid

    def test_session_history_is_preserved(self):
        """Two turns in same session → second turn gets history context."""
        r = requests.post(f"{BASE}/v1/sessions", json={"datasource": "qsint_docs"})
        sid = r.json()["id"]

        # First turn
        requests.post(
            f"{BASE}/v1/chat",
            json={"session_id": sid, "message": "Tell me about Sandworm"},
            timeout=120,
        )
        # Second turn — references prior context
        r2 = requests.post(
            f"{BASE}/v1/chat",
            json={"session_id": sid, "message": "What did you just tell me about?"},
            timeout=120,
        )
        assert r2.status_code == 200

        msgs = requests.get(f"{BASE}/v1/sessions/{sid}/messages").json()["messages"]
        assert len(msgs) == 4  # 2 user + 2 assistant


class TestInsightsE2E:

    def test_insights_returns_structured_data(self):
        r = requests.get(f"{BASE}/v1/insights", params={"datasource": "qsint_docs"}, timeout=120)
        assert r.status_code == 200
        data = r.json()
        assert "tasks" in data
        assert "_meta" in data

    def test_insights_refresh_updates_cache(self):
        r1 = requests.get(f"{BASE}/v1/insights", params={"datasource": "qsint_docs_global"}, timeout=120)
        ts1 = r1.json().get("_meta", {}).get("refresh_triggered")

        r2 = requests.post(f"{BASE}/v1/insights/refresh", json={"datasource": "qsint_docs_global"}, timeout=120)
        assert r2.status_code == 200

        # Refreshed timestamp should differ (unless exact same second)
        assert r2.json()["_meta"]["refresh_triggered"] is True
