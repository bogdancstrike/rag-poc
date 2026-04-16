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
        assert "APT28" in last_content

    def test_chunk_text_appears_in_message(self, builder):
        chunks = [{"id": "abc123", "text": "Unique text about alpha bravo.", "score": 0.9, "source": "es", "metadata": {}}]
        messages, _ = builder.build_chat_messages("query", chunks, [])
        last_content = messages[-1]["content"]
        assert "Unique text about alpha bravo" in last_content

    def test_empty_chunks_produces_no_context_message(self, builder):
        messages, _ = builder.build_chat_messages("query", [], [])
        last_content = messages[-1]["content"]
        assert "No relevant documents" in last_content

    def test_empty_history_produces_single_user_message(self, builder, sample_chunks):
        messages, _ = builder.build_chat_messages("query", sample_chunks, [])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_multiple_chunks_all_appear_in_context(self, builder, sample_chunks):
        messages, _ = builder.build_chat_messages("query", sample_chunks, [])
        content = messages[-1]["content"]
        assert "APT28" in content
        assert "Fancy Bear" in content

    def test_history_order_preserved(self, builder, sample_chunks, sample_history):
        messages, _ = builder.build_chat_messages("Final?", sample_chunks, sample_history)
        # History messages appear before the final user message
        user_indices = [i for i, m in enumerate(messages) if m["role"] == "user"]
        assert user_indices[-1] == len(messages) - 1  # last message is current query


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

    def test_doc_text_appears_in_message(self, builder):
        """Doc text (not necessarily ID) should appear in the corpus message."""
        docs = [{"id": "abc123", "text": "Test document unique phrase xyz.", "score": 1.0}]
        messages, _ = builder.build_insights_messages(docs)
        assert "Test document unique phrase xyz" in messages[0]["content"]

    def test_long_text_is_truncated(self, builder):
        long_text = "A" * 2000
        docs = [{"id": "d1", "text": long_text, "score": 1.0}]
        messages, _ = builder.build_insights_messages(docs)
        assert len(messages[0]["content"]) < len(long_text) * 2

    def test_graph_task_type_changes_user_message(self, builder):
        docs = [{"id": "d1", "text": "Entity relationship text.", "score": 1.0}]
        msgs_summary, _ = builder.build_insights_messages(docs, task_type="summary")
        msgs_graph, _   = builder.build_insights_messages(docs, task_type="graph")
        # The user message content embeds the task-specific schema — should differ by type
        assert msgs_summary[0]["content"] != msgs_graph[0]["content"]

    def test_all_ai_tasks_use_32k_cap(self, builder):
        # Create many large documents to exceed any token budget.
        # Both task types should be capped well below 100 docs.
        from src.config import Config
        old_ctx = Config.LLM_INSIGHTS_CTX
        Config.LLM_INSIGHTS_CTX = 65536

        try:
            large_text = "A" * 5000
            docs = [{"id": f"d{i}", "text": large_text, "score": 1.0} for i in range(100)]

            msgs_trend, _ = builder.build_insights_messages(docs, task_type="trending_signals")
            msgs_graph, _ = builder.build_insights_messages(docs, task_type="relationship_network")

            def get_doc_count(content):
                import re
                match = re.search(r"=== INTELLIGENCE CORPUS \((\d+) documents\)", content)
                return int(match.group(1)) if match else 0

            # Each task is capped — neither packs all 100 docs
            assert get_doc_count(msgs_trend[0]["content"]) < 100
            assert get_doc_count(msgs_graph[0]["content"]) < 100
            # relationship_network has larger schema overhead so may pack fewer docs than trending_signals
        finally:
            Config.LLM_INSIGHTS_CTX = old_ctx

    def test_empty_docs_still_returns_valid_structure(self, builder):
        messages, system = builder.build_insights_messages([])
        assert isinstance(messages, list)
        assert isinstance(system, str)

    def test_build_field_enrichment_messages_returns_tuple(self, builder):
        messages, system = builder.build_field_enrichment_messages("Some text about threats.", "sentiment")
        assert isinstance(messages, list)
        assert isinstance(system, str)
        assert len(messages) > 0

    def test_field_enrichment_includes_field_name(self, builder):
        messages, _ = builder.build_field_enrichment_messages("Text here.", "classification")
        content_combined = " ".join(m["content"] for m in messages)
        assert "classification" in content_combined.lower() or "classification" in _


class TestBuildFieldEnrichment:

    def test_all_supported_fields_produce_output(self, builder):
        fields = ["sentiment", "classification", "summary", "entities", "iocs", "graph", "timeline", "translation"]
        for field in fields:
            msgs, sys = builder.build_field_enrichment_messages("Test intelligence text.", field)
            assert len(msgs) > 0, f"No messages for field={field}"
            assert isinstance(sys, str)
