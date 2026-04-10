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
  "hot_topics": [{"topic": "string", "count_estimate": int, "summary": "string", "sentiment": "positive|negative|neutral|mixed"}],
  "narratives": [{"title": "string", "description": "string", "evidence_docs": ["doc_id"]}],
  "trends": [{"label": "string", "direction": "rising|falling|stable", "change_pct": float, "time_period": "string"}]
}
3. Do NOT include any other keys like "summary" or "key_findings" at the top level.
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

INSIGHTS_GRAPH_PROMPT = """Detect relationships and connections between entities in the documents.
FORMAT RULES:
1. Output ONLY valid JSON.
2. The JSON must have EXACTLY this structure:
{
  "nodes": [{"id": "string", "label": "string", "type": "string"}],
  "edges": [{"source": "string", "target": "string", "relationship": "string", "weight": float}]
}
3. Do NOT include any other keys like "summary" or "key_findings" at the top level.
"""


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
        """Build the messages list for single document enrichment."""
        messages = [{
            "role": "user",
            "content": f"Document:\n{document_text}\n\n---\nAnalyze the above document and output structured JSON.\n\nREQUIRED SCHEMA (You MUST output ONLY valid JSON matching this exact structure):\n{INSIGHTS_ENRICH_PROMPT}",
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
