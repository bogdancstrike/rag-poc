"""Unit tests for session_service using a real SQLite in-memory database.

We override Config.DATABASE_URL before importing models so SQLite is used.
"""
import os
import pytest

# Point DB at in-memory SQLite before importing anything that touches Config
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from src.session.models import init_db, Base, get_engine
from src.session.session_service import (
    create_session,
    get_session,
    list_sessions,
    delete_session,
    update_session_title,
    append_message,
    get_messages,
    get_recent_messages,
)


@pytest.fixture(autouse=True)
def fresh_db():
    """Create all tables before each test and drop after."""
    init_db()
    yield
    Base.metadata.drop_all(bind=get_engine())


class TestCreateSession:

    def test_creates_session_with_defaults(self):
        s = create_session()
        assert s["id"]
        assert s["datasource"] == "default"
        assert s["title"] is None

    def test_creates_session_with_title(self):
        s = create_session(title="My investigation", datasource="qsint_docs")
        assert s["title"] == "My investigation"
        assert s["datasource"] == "qsint_docs"

    def test_ids_are_unique(self):
        ids = {create_session()["id"] for _ in range(10)}
        assert len(ids) == 10


class TestGetSession:

    def test_returns_existing_session(self):
        s = create_session(title="test")
        found = get_session(s["id"])
        assert found is not None
        assert found["id"] == s["id"]

    def test_returns_none_for_missing(self):
        assert get_session("nonexistent-id") is None


class TestListSessions:

    def test_lists_all_sessions(self):
        create_session()
        create_session()
        sessions = list_sessions()
        assert len(sessions) >= 2

    def test_filters_by_datasource(self):
        create_session(datasource="es1")
        create_session(datasource="es2")
        result = list_sessions(datasource="es1")
        assert all(s["datasource"] == "es1" for s in result)

    def test_respects_limit(self):
        for _ in range(10):
            create_session()
        assert len(list_sessions(limit=3)) == 3


class TestDeleteSession:

    def test_deletes_existing(self):
        s = create_session()
        assert delete_session(s["id"]) is True
        assert get_session(s["id"]) is None

    def test_returns_false_for_missing(self):
        assert delete_session("no-such-id") is False


class TestUpdateSessionTitle:

    def test_renames_session(self):
        s = create_session(title="old")
        updated = update_session_title(s["id"], "new title")
        assert updated["title"] == "new title"

    def test_returns_none_for_missing(self):
        assert update_session_title("no-id", "title") is None


class TestAppendMessage:

    def test_appends_user_message(self):
        s = create_session()
        m = append_message(s["id"], "user", "Hello")
        assert m["role"] == "user"
        assert m["content"] == "Hello"

    def test_appends_assistant_with_sources(self):
        s = create_session()
        sources = [{"id": "d1", "score": 0.9, "text": "snippet"}]
        m = append_message(s["id"], "assistant", "Reply", sources=sources)
        assert m["sources"] == sources

    def test_auto_titles_from_first_user_message(self):
        s = create_session()
        append_message(s["id"], "user", "What is APT28?")
        updated = get_session(s["id"])
        assert "APT28" in updated["title"]

    def test_raises_for_missing_session(self):
        with pytest.raises(ValueError):
            append_message("no-session", "user", "msg")


class TestGetMessages:

    def test_returns_in_chronological_order(self):
        s = create_session()
        append_message(s["id"], "user", "First")
        append_message(s["id"], "assistant", "Second")
        append_message(s["id"], "user", "Third")
        msgs = get_messages(s["id"])
        assert [m["content"] for m in msgs] == ["First", "Second", "Third"]

    def test_empty_for_new_session(self):
        s = create_session()
        assert get_messages(s["id"]) == []


class TestGetRecentMessages:

    def test_returns_last_n_turns(self):
        s = create_session()
        for i in range(10):
            append_message(s["id"], "user", f"Q{i}")
            append_message(s["id"], "assistant", f"A{i}")
        recent = get_recent_messages(s["id"], turns=3)
        # 3 turns × 2 messages = up to 6, in chronological order
        assert len(recent) <= 6

    def test_returns_chronological_order(self):
        s = create_session()
        append_message(s["id"], "user", "First user")
        append_message(s["id"], "assistant", "First assistant")
        recent = get_recent_messages(s["id"], turns=5)
        assert recent[0]["role"] == "user"
        assert recent[1]["role"] == "assistant"
