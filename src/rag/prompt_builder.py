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

INSIGHTS_SUMMARY_PROMPT = """You are a specialized intelligence extraction engine.
Analyse the provided documents and output structured insights.

FORMAT RULES:
1. Output ONLY valid JSON.
2. The JSON must have EXACTLY this structure:
{
  "hot_topics": [{"topic": "string", "count_estimate": int, "summary": "string", "sentiment": "positive|negative|neutral|mixed|hostile"}],
  "narratives": [{"title": "string", "description": "string", "evidence_docs": ["doc_title_or_keyword"]}],
  "trends": [{"label": "string", "direction": "rising|falling|stable", "change_pct": float, "time_period": "string"}]
}
3. Do NOT include any other keys like "summary" or "key_findings" at the top level.
4. Return UP TO 10 hot_topics (most significant first), UP TO 5 narratives (most impactful first), UP TO 10 trends.
"""

INSIGHTS_NER_PROMPT = """Extract named entities from the provided documents.
FORMAT RULES:
1. Output ONLY valid JSON.
2. The JSON must have EXACTLY this structure:
{
  "entities": [{"name": "string", "type": "person|org|location|event|tool|vulnerability", "frequency": int, "sentiment": "string"}]
}
3. Do NOT include any other keys like "summary" or "key_findings" at the top level.
"""

INSIGHTS_GRAPH_PROMPT = """Detect relationships between named entities (people, organizations, locations, tools, events) in the documents.
Build a concise knowledge graph — do NOT use document IDs as node IDs.

FORMAT RULES:
1. Output ONLY valid JSON, no markdown, no comments.
2. Use the entity name itself as the node "id" (e.g., "LockBit", "SVR", "Ukraine").
3. Limit to 10-15 nodes and at most 20 edges.
4. The JSON must have EXACTLY this structure:
{
  "nodes": [{"id": "EntityName", "label": "EntityName", "type": "person|org|location|tool|event"}],
  "edges": [{"source": "EntityName1", "target": "EntityName2", "relationship": "string", "weight": 0.8}]
}
5. "source" and "target" in edges MUST match node "id" values exactly.
6. Do NOT include any other top-level keys.
"""

# ── Per-field enrichment prompts ───────────────────────────────────────────────

ENRICH_SENTIMENT_PROMPT = """Analyze the sentiment of the document.
Output ONLY valid JSON: {"sentiment": "positive|negative|neutral|mixed|hostile"}"""

ENRICH_CLASSIFICATION_PROMPT = """Classify the document into an intelligence category.
Output ONLY valid JSON: {"classification": "string (e.g., Cyber Threat, Geopolitics, Financial Crime, Intelligence Report, Disinformation)"}"""

ENRICH_ENTITIES_PROMPT = """Extract named entities (people, organizations, locations, tools) from the document.
Output ONLY valid JSON: {"entities": [{"name": "string", "type": "person|org|location|tool"}]}"""

ENRICH_SUMMARY_PROMPT = """Write a concise 1-2 sentence intelligence summary of the document.
Output ONLY valid JSON: {"summary": "string"}"""


INSIGHTS_ENRICH_PROMPT = """You are an expert intelligence analyst. 
Analyze the following document and extract key enrichments.

FORMAT RULES:
1. Output ONLY valid JSON.
2. The JSON must have EXACTLY this structure:
{
  "summary": "string (1-2 sentences)",
  "sentiment": "positive|negative|neutral|mixed",
  "classification": "string (e.g., Cyber Threat, Geopolitics, Financial Crime)",
  "entities": [{"name": "string", "type": "person|org|location|tool"}]
}
3. Do NOT include any other keys.
"""

class PromptBuilder:
    """Assembles LLM-ready messages from retrieved chunks + conversation history."""

    def build_enrichment_messages(self, document_text: str) -> tuple[list[dict], str]:
        """Build the messages list for full document enrichment (all fields at once)."""
        messages = [{
            "role": "user",
            "content": (
                f"Document:\n{document_text}\n\n---\n"
                "Analyze the above document and output structured JSON.\n\n"
                f"REQUIRED SCHEMA (output ONLY this JSON, no extra text):\n{INSIGHTS_ENRICH_PROMPT}"
            ),
        }]
        return messages, "You are a specialized JSON extraction engine. Output ONLY valid JSON."

    def build_field_enrichment_messages(self, document_text: str, field: str) -> tuple[list[dict], str]:
        """Build messages for a single enrichment field (sentiment / classification / entities / summary).

        Args:
            document_text: The document content to analyze.
            field: One of 'sentiment', 'classification', 'entities', 'summary'.
        """
        field_prompt_map = {
            "sentiment":      ENRICH_SENTIMENT_PROMPT,
            "classification": ENRICH_CLASSIFICATION_PROMPT,
            "entities":       ENRICH_ENTITIES_PROMPT,
            "summary":        ENRICH_SUMMARY_PROMPT,
        }
        prompt = field_prompt_map.get(field, INSIGHTS_ENRICH_PROMPT)
        messages = [{
            "role": "user",
            "content": f"Document:\n{document_text}\n\n---\n{prompt}",
        }]
        return messages, "You are a specialized JSON extraction engine. Output ONLY valid JSON."

    # ── Chat prompt ─────────────────────────────────────────────────────────────

    def build_chat_messages(
        self,
        user_query: str,
        chunks: list[dict],
        history: list[dict],
    ) -> tuple[list[dict], str]:
        context_block = self._format_chunks(chunks)

        messages: list[dict] = []
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        user_content = f"Context documents:\n{context_block}\n\nQuestion: {user_query}"
        messages.append({"role": "user", "content": user_content})

        return messages, RAG_SYSTEM_PROMPT

    # ── Insights prompt ─────────────────────────────────────────────────────────

    def build_insights_messages(self, sample_docs: list[dict], task_type: str = "summary") -> tuple[list[dict], str]:
        """Build the messages list for the insights generation call."""
        doc_texts = "\n\n".join(
            f'<doc id="{doc["id"]}">{doc["text"][:300]}</doc>'
            for doc in sample_docs[:Config.INSIGHTS_MAX_DOCS]
        )

        prompt_map = {
            "summary": INSIGHTS_SUMMARY_PROMPT,
            "ner":     INSIGHTS_NER_PROMPT,
            "graph":   INSIGHTS_GRAPH_PROMPT,
        }
        system_prompt = prompt_map.get(task_type, INSIGHTS_SUMMARY_PROMPT)

        messages = [{
            "role": "user",
            "content": f"Documents:\n{doc_texts}\n\n---\nAnalyse the above {len(sample_docs)} documents and output structured JSON for {task_type}.\n\nREQUIRED SCHEMA (You MUST output ONLY valid JSON matching this exact structure):\n{system_prompt}",
        }]

        return messages, "You are a specialized JSON extraction engine. Output ONLY valid JSON."

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_chunks(chunks: list[dict]) -> str:
        if not chunks:
            return "<context>No relevant documents found.</context>"

        parts = []
        for chunk in chunks:
            doc_id = chunk.get("id", "unknown")
            score  = chunk.get("score", 0)
            text   = chunk.get("text", "").strip()
            parts.append(f'<doc id="{doc_id}" relevance="{score:.2f}">\n{text}\n</doc>')
        return "\n\n".join(parts)
