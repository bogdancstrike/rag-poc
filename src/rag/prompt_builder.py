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
  "hot_topics": [{"topic": "string", "count_estimate": int, "summary": "string", "sentiment": "positive|negative|neutral"}],
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

INSIGHTS_GRAPH_PROMPT = """Detect relationships between named entities (people, organizations, locations, tools, events) across ALL provided documents.
Build a rich knowledge graph that captures the full breadth of relationships in the corpus — do NOT use document IDs as node IDs.

FORMAT RULES:
1. Output ONLY valid JSON, no markdown, no comments.
2. Use the entity name itself as the node "id" (e.g., "LockBit", "SVR", "Ukraine").
3. Aim for 30-60 nodes and 60-120 edges. More is better — cover the full corpus.
4. Assign each node a "community" integer (0-based) grouping related entities into discovered communities/clusters.
5. The JSON must have EXACTLY this structure:
{
  "nodes": [{"id": "EntityName", "label": "EntityName", "type": "person|org|location|tool|event", "community": 0}],
  "edges": [{"source": "EntityName1", "target": "EntityName2", "relationship": "string", "weight": 0.8}]
}
6. "source" and "target" in edges MUST match node "id" values exactly.
7. Do NOT include any other top-level keys.
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
Analyze the following document and extract structured intelligence enrichments.

FORMAT RULES:
1. Output ONLY valid JSON, no markdown fences.
2. The JSON must have EXACTLY this structure:
{
  "summary": "string (2-3 sentences)",
  "sentiment": "positive|negative|neutral|mixed|hostile|supportive",
  "classification": "string (e.g., Cyber Threat, Geopolitics, Disinformation, Financial Crime)",
  "entities": [{"name": "string", "type": "person|org|location|tool|event|vulnerability"}],
  "graph": {
    "nodes": [{"id": "string", "label": "string", "type": "person|org|location|tool|event", "community": 0}],
    "edges": [{"source": "string", "target": "string", "relationship": "string", "weight": 0.8}]
  },
  "timeline": [{"date": "string (as written in document)", "description": "string", "normalized": "ISO 8601 or null"}],
  "locations": ["place name 1", "place name 2"],
  "language": "ISO 639-1 code of the document primary language"
}
3. "graph": 3-15 nodes (key entities), 3-20 edges (relationships). source/target must match node ids.
4. "timeline": ALL date/time references found in the document.
5. "locations": ONLY geographic place names (cities, countries, regions) — just names, no coordinates.
6. "language": primary language code (e.g. "en", "ro", "fr", "ar", "ru").
7. Do NOT include any other top-level keys.
"""

ENRICH_GRAPH_PROMPT = """Extract a knowledge graph of entities and their relationships from the document.
Output ONLY valid JSON:
{
  "graph": {
    "nodes": [{"id": "EntityName", "label": "EntityName", "type": "person|org|location|tool|event", "community": 0}],
    "edges": [{"source": "EntityName1", "target": "EntityName2", "relationship": "string", "weight": 0.8}]
  }
}
Aim for 5-15 nodes and 5-20 edges. source/target must match node ids exactly."""

ENRICH_TIMELINE_PROMPT = """Extract all temporal references from the document (dates, time periods, events with timestamps).
Output ONLY valid JSON:
{"timeline": [{"date": "string (as in document)", "description": "string (what happened)", "normalized": "ISO 8601 or null"}]}"""

ENRICH_LOCATIONS_PROMPT = """Extract all geographic locations mentioned in the document.
Output ONLY valid JSON: {"locations": ["location name 1", "location name 2"]}
List only distinct place names (cities, countries, regions). Do not include coordinates."""

ENRICH_TRANSLATION_PROMPT = """Translate the following text to Romanian language.
Output ONLY valid JSON: {"text": "Romanian translation here"}
If the text is already in Romanian, return it unchanged. Preserve structure and meaning."""

class PromptBuilder:
    """Assembles LLM-ready messages from retrieved chunks + conversation history."""

    def build_enrichment_messages(self, document_text: str) -> tuple[list[dict], str]:
        """Build the messages list for full document enrichment (all fields at once).

        Document text goes AFTER the schema so the model reads instruction → schema
        → document in order. When thinking is suppressed (/no_think) the model
        would otherwise interpret "Analyze the following document..." (embedded in
        the schema prompt) as a new instruction expecting more input, and reply with
        a "ready" template instead of performing the extraction.
        """
        messages = [{
            "role": "user",
            "content": (
                "Extract structured intelligence from the document text at the bottom.\n"
                "Return ONLY a valid JSON object matching this schema exactly:\n\n"
                f"{INSIGHTS_ENRICH_PROMPT}\n\n"
                f"=== DOCUMENT ===\n{document_text}"
            ),
        }]
        return messages, "You are a specialized JSON extraction engine. Output ONLY valid JSON."

    def build_field_enrichment_messages(self, document_text: str, field: str) -> tuple[list[dict], str]:
        """Build messages for a single enrichment field reload."""
        field_prompt_map = {
            "sentiment":      ENRICH_SENTIMENT_PROMPT,
            "classification": ENRICH_CLASSIFICATION_PROMPT,
            "entities":       ENRICH_ENTITIES_PROMPT,
            "summary":        ENRICH_SUMMARY_PROMPT,
            "graph":          ENRICH_GRAPH_PROMPT,
            "timeline":       ENRICH_TIMELINE_PROMPT,
            "locations":      ENRICH_LOCATIONS_PROMPT,
        }
        prompt = field_prompt_map.get(field, INSIGHTS_ENRICH_PROMPT)
        messages = [{
            "role": "user",
            "content": f"{prompt}\n\n=== DOCUMENT ===\n{document_text}",
        }]
        return messages, "You are a specialized JSON extraction engine. Output ONLY valid JSON."

    def build_translation_messages(self, document_text: str) -> tuple[list[dict], str]:
        """Build messages to translate a document to Romanian."""
        messages = [{
            "role": "user",
            "content": f"{ENRICH_TRANSLATION_PROMPT}\n\n=== TEXT TO TRANSLATE ===\n{document_text}",
        }]
        return messages, "You are a professional translator. Output ONLY valid JSON."

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
        """Build the messages list for the insights generation call.

        Sends lightweight one-line entries (title + topic + sentiment + 120-char
        snippet) instead of full text so that up to 500 documents fit within the
        LLM context window while still giving the model the breadth of the corpus.
        """
        docs = sample_docs[:Config.INSIGHTS_MAX_DOCS]

        def _fmt(doc: dict) -> str:
            title     = (doc.get("title") or "").strip()[:80]
            topic     = doc.get("topic", "")
            sentiment = doc.get("sentiment", "")
            snippet   = (doc.get("text") or "").strip()[:120].replace("\n", " ")
            parts = []
            if title:     parts.append(f"title={title!r}")
            if topic:     parts.append(f"topic={topic!r}")
            if sentiment: parts.append(f"sentiment={sentiment!r}")
            if snippet:   parts.append(f"snippet={snippet!r}")
            return f"[{', '.join(parts)}]"

        doc_lines = "\n".join(_fmt(d) for d in docs)

        prompt_map = {
            "summary": INSIGHTS_SUMMARY_PROMPT,
            "graph":   INSIGHTS_GRAPH_PROMPT,
        }
        system_prompt = prompt_map.get(task_type, INSIGHTS_SUMMARY_PROMPT)

        messages = [{
            "role": "user",
            "content": (
                f"Analyse ALL {len(docs)} documents below and output structured JSON for {task_type}.\n"
                f"Return ONLY a valid JSON object matching this schema exactly:\n\n"
                f"{system_prompt}\n\n"
                f"=== CORPUS ({len(docs)} documents) ===\n{doc_lines}"
            ),
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
