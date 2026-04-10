"""Prompt assembly for the RAG pipeline.

Builds the system prompt and the messages list that gets sent to the LLM.
Retrieved document chunks are embedded as XML-tagged blocks so the model
can cite them precisely.
"""
from src.config import Config


# ── System prompts ─────────────────────────────────────────────────────────────

RAG_SYSTEM_PROMPT = """You are QSINT, an intelligence analyst assistant.
Your role is to help analysts understand and explore data from the QSINT platform.

Rules:
- Answer ONLY using the provided context documents. Do NOT fabricate facts.
- If the answer is not in the context, say "I don't have enough information in the provided documents to answer that."
- When referencing specific information, cite the document ID in the format [doc:ID].
- Be concise and analytical. Prioritise key findings over exhaustive summaries.
- Use markdown for structure when it aids clarity (bullet points, bold key terms).
"""

INSIGHTS_SYSTEM_PROMPT = """You are an intelligence analysis engine for the QSINT platform.
Analyse the provided document sample and extract structured intelligence.

Return ONLY valid JSON with this exact structure:
{
  "hot_topics": [
    {"topic": "string", "count_estimate": int, "summary": "string", "sentiment": "positive|negative|neutral|mixed"}
  ],
  "narratives": [
    {"title": "string", "description": "string", "evidence_docs": ["doc_id1", "doc_id2"]}
  ],
  "trends": [
    {"label": "string", "direction": "rising|falling|stable", "change_pct": float, "time_period": "string"}
  ],
  "entities": [
    {"name": "string", "type": "person|org|location|event|other", "frequency": int, "related": ["string"]}
  ],
  "anomalies": [
    {"description": "string", "docs": ["doc_id1"]}
  ]
}

Be specific and grounded in the documents. Aim for 5-10 items per category where data permits.
"""


class PromptBuilder:
    """Assembles LLM-ready messages from retrieved chunks + conversation history."""

    # ── Chat prompt ─────────────────────────────────────────────────────────────

    def build_chat_messages(
        self,
        user_query: str,
        chunks: list[dict],
        history: list[dict],
    ) -> tuple[list[dict], str]:
        """Build the messages list and system prompt for a chat turn.

        Args:
            user_query: The user's current question.
            chunks:     Retrieved document chunks [{id, text, score, ...}].
            history:    Previous messages from Postgres [{role, content}].

        Returns:
            (messages, system_prompt) ready to pass to LLMClient.complete() or .stream()
        """
        context_block = self._format_chunks(chunks)

        # Build conversation history (excluding the current query)
        messages: list[dict] = []
        for msg in history:
            messages.append({
                "role":    msg["role"],
                "content": msg["content"],
            })

        # The current user message includes the retrieved context
        user_content = f"""Context documents:
{context_block}

Question: {user_query}"""

        messages.append({"role": "user", "content": user_content})

        return messages, RAG_SYSTEM_PROMPT

    # ── Insights prompt ─────────────────────────────────────────────────────────

    def build_insights_messages(self, sample_docs: list[dict]) -> tuple[list[dict], str]:
        """Build the messages list for the insights generation call.

        Args:
            sample_docs: Random sample of documents from the corpus.

        Returns:
            (messages, system_prompt) ready to pass to LLMClient.complete_json()
        """
        doc_texts = "\n\n".join(
            f'<doc id="{doc["id"]}">{doc["text"][:300]}</doc>'
            for doc in sample_docs[:Config.INSIGHTS_MAX_DOCS]
        )

        messages = [{
            "role": "user",
            "content": f"Analyse these {len(sample_docs)} documents and extract structured intelligence:\n\n{doc_texts}",
        }]

        return messages, INSIGHTS_SYSTEM_PROMPT

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_chunks(chunks: list[dict]) -> str:
        """Format retrieved chunks as XML doc blocks for the LLM context."""
        if not chunks:
            return "<context>No relevant documents found.</context>"

        parts = []
        for chunk in chunks:
            doc_id = chunk.get("id", "unknown")
            score  = chunk.get("score", 0)
            text   = chunk.get("text", "").strip()
            parts.append(
                f'<doc id="{doc_id}" relevance="{score:.2f}">\n{text}\n</doc>'
            )
        return "\n\n".join(parts)
