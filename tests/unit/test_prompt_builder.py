"""Unit tests for PromptBuilder.

No external dependencies — tests message assembly logic in isolation.
"""
import pytest
from src.rag.prompt_builder import PromptBuilder


@pytest.fixture
def builder():
    return PromptBuilder()


@pytest.fixture
def sample_chunks():
    return [
        {"id": "doc1", "text": "APT28 conducts phishing campaigns.", "score": 0.95, "source": "es", "metadata": {}},
        {"id": "doc2", "text": "Fancy Bear is linked to GRU.", "score": 0.80, "source": "es", "metadata": {}},
    ]


@pytest.fixture
def sample_history():
    return [
        {"role": "user",      "content": "Tell me about APT28."},
        {"role": "assistant", "content": "APT28 is a Russian threat actor."},
    ]


class TestBuildChatMessages:

    def test_returns_tuple_of_messages_and_system(self, builder, sample_chunks, sample_history):
        messages, system = builder.build_chat_messages("What platforms?", sample_chunks, sample_history)
        assert isinstance(messages, list)
        assert isinstance(system, str)
        assert len(system) > 0

    def test_system_prompt_contains_qsint(self, builder, sample_chunks, sample_history):
        _, system = builder.build_chat_messages("query", sample_chunks, sample_history)
        assert "QSINT" in system

    def test_history_is_injected_into_messages(self, builder, sample_chunks, sample_history):
        messages, _ = builder.build_chat_messages("New question?", sample_chunks, sample_history)
        roles = [m["role"] for m in messages]
        # history + current user message
        assert roles.count("user") >= 2
        assert roles.count("assistant") >= 1

    def test_current_query_is_last_message(self, builder, sample_chunks, sample_history):
        query = "What is the latest threat?"
        messages, _ = builder.build_chat_messages(query, sample_chunks, sample_history)
        assert messages[-1]["role"] == "user"
        assert query in messages[-1]["content"]

    def test_chunks_are_embedded_in_user_message(self, builder, sample_chunks):
        messages, _ = builder.build_chat_messages("query", sample_chunks, [])
        last_content = messages[-1]["content"]
        assert "doc1" in last_content
        assert "doc2" in last_content
        assert "APT28" in last_content

    def test_empty_chunks_produces_no_context_message(self, builder):
        messages, _ = builder.build_chat_messages("query", [], [])
        last_content = messages[-1]["content"]
        assert "No relevant documents" in last_content

    def test_empty_history_produces_single_user_message(self, builder, sample_chunks):
        messages, _ = builder.build_chat_messages("query", sample_chunks, [])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


class TestBuildInsightsMessages:

    def test_returns_messages_and_system(self, builder):
        docs = [{"id": "d1", "text": "Some intelligence text.", "score": 1.0}]
        messages, system = builder.build_insights_messages(docs)
        assert isinstance(messages, list)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "QSINT" in system or "JSON" in system

    def test_doc_count_in_message(self, builder):
        docs = [{"id": f"d{i}", "text": f"Doc {i}", "score": 1.0} for i in range(5)]
        messages, _ = builder.build_insights_messages(docs)
        assert "5" in messages[0]["content"]

    def test_doc_ids_in_message(self, builder):
        docs = [{"id": "abc123", "text": "Test document.", "score": 1.0}]
        messages, _ = builder.build_insights_messages(docs)
        assert "abc123" in messages[0]["content"]

    def test_long_text_is_truncated(self, builder):
        long_text = "A" * 2000
        docs = [{"id": "d1", "text": long_text, "score": 1.0}]
        messages, _ = builder.build_insights_messages(docs)
        # text is capped at 600 chars per doc
        assert len(messages[0]["content"]) < len(long_text) * 2
