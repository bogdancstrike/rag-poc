"""Prompt assembly for the RAG pipeline.

Builds the system prompt and the messages list that gets sent to the LLM.
Retrieved document chunks are embedded as XML-tagged blocks so the model
can cite them precisely.
"""
from framework.commons.logger import logger
from src.config import Config


# ── System prompts ─────────────────────────────────────────────────────────────

RAG_SYSTEM_PROMPT = """You are QSINT, an intelligence analyst assistant.
Your role is to help analysts understand and explore data from the QSINT intelligence platform.

STRICT RULES:
1. Answer ONLY using information from the provided <doc> context blocks. Never use outside knowledge or fabricate facts.
2. If the documents do not contain enough information to answer, say exactly: "The provided documents do not contain enough information to answer this question."
3. Cite every claim inline using the document id attribute: [doc:ID]. If a doc has a title attribute, prefer [doc:ID "Title"]. Cite ALL documents that support each point.
4. Do NOT summarise every document — synthesise a direct answer to the question, citing only the relevant parts.
5. Use markdown structure (bullet points, **bold** key terms, headings) when it improves clarity.
6. Never invent document IDs or cite documents not in the provided context.
"""

INSIGHTS_TRENDING_SIGNALS_SCHEMA = """{
  "trending_signals": [
    {"label": "string", "direction": "rising|falling|stable", "change_summary": "string", "key_evidence": "string"}
  ]
}"""

INSIGHTS_TRENDING_SIGNALS_RULES = """Rules:
- Identify rising or falling signals based on frequency, recency, and urgency.
- Look for emerging threats, shifts in actor behavior, or new geopolitical developments.
- Up to 8 signals, most significant first."""

INSIGHTS_ACTIVE_NARRATIVES_SCHEMA = """{
  "active_narratives": [
    {"title": "string", "description": "string", "sentiment": "string", "key_actors": ["string"]}
  ]
}"""

INSIGHTS_ACTIVE_NARRATIVES_RULES = """Rules:
- Discover high-level storylines or disinformation campaigns running through the documents.
- Identify the core message, its sentiment, and the primary actors involved.
- Up to 5 narratives."""

INSIGHTS_HOT_TOPICS_SENTIMENT_SCHEMA = """{
  "hot_topics": [
    {"topic": "string", "sentiment_score": 0.0, "sentiment_label": "positive|negative|neutral|hostile", "brief_context": "string"}
  ]
}"""

INSIGHTS_HOT_TOPICS_SENTIMENT_RULES = """Rules:
- List discrete topics mentioned across the corpus.
- sentiment_score: -1.0 (hostile) to 1.0 (positive).
- brief_context: 1 sentence explaining the topic's relevance.
- Up to 15 topics."""

INSIGHTS_NER_PROMPT = """Extract named entities from the provided documents.
FORMAT RULES:
1. Output ONLY valid JSON.
2. The JSON must have EXACTLY this structure:
{
  "entities": [{"name": "string", "type": "person|org|location|event|tool|vulnerability", "frequency": int, "sentiment": "string"}]
}
3. Do NOT include any other keys like "summary" or "key_findings" at the top level.
"""

INSIGHTS_GRAPH_PROMPT = """Detect communities of related entities across ALL provided documents and build a knowledge graph centred on those communities.

OBJECTIVE: First extract Named Entities (NER) from the documents, then discover clusters (communities) of those entities that share significant relationships. Prioritise entities with multiple connections — isolated nodes with no edges add no value and should be omitted.

==========================================================
PHASE 1 — NAMED ENTITY RECOGNITION (MANDATORY FIRST STEP)
==========================================================
Before constructing ANY graph, perform Named Entity Recognition over the full document set. Extract ONLY entities that fall into one of the following categories. Any token/phrase that does not match one of these categories MUST be ignored and MUST NOT appear in the graph.

Allowed entity categories (these are the ONLY permitted node types):

1. PERSON — Named individuals (politicians, executives, suspects, journalists, researchers, etc.).
   Example: "Vladimir Putin", "Elon Musk".

2. ORG (ORGANIZATION) — Companies, government agencies, NGOs, political parties, military units, intelligence services, threat actor groups, terrorist organisations.
   Example: "Gazprom", "SVR", "LockBit", "European Commission".

3. GPE (Geo-Political Entity) — Politically defined places: countries, cities, states, regions with governance.
   Example: "Ukraine", "Bucharest", "California".

4. LOC (LOCATION) — Non-political geography: mountains, rivers, seas, continents, named natural areas.
   Example: "Black Sea", "Carpathians".

5. DATE — Temporal expressions: absolute dates, relative dates, quarters, years, named periods.
   Example: "March 15 2026", "Q3 2026", "yesterday".

6. MONEY — Financial amounts and currencies.
   Example: "€2.5 million", "$10,000".

7. EVENT — Named real-world events: elections, summits, attacks, protests, conferences, operations, incidents.
   Example: "KubeCon 2026", "January 6th", "Operation Aurora".

8. PRODUCT — Commercial products, software, weapons systems, vehicles, malware families, platforms.
   Example: "F-35", "ChatGPT", "iPhone", "Cobalt Strike".

9. NORP — Nationalities, Religious or Political groups (collective identities, NOT individuals or formal orgs).
   Example: "Romanians", "Catholics", "Democrats".

10. LAW — Named laws, treaties, regulations, court cases, directives.
    Example: "GDPR", "NIS2", "Roe v. Wade".

11. FAC (FACILITY) — Buildings, airports, highways, bridges, military bases, ports, named physical infrastructure.
    Example: "Pentagon", "Otopeni Airport", "Nord Stream pipeline".

NER RULES:
- Extract entities EXACTLY as they appear in the source text. Do NOT normalise to canonical real-world forms.
- You MAY merge obvious aliases (e.g., "EU" and "European Union") only if BOTH forms appear in the documents; otherwise keep the surface form used in the text.
- Do NOT extract generic nouns ("the company", "the president") unless the document attaches a specific name.
- Do NOT invent, infer, or hallucinate entities. If it is not literally in the text, it does not exist.
- Discard any candidate entity that does not cleanly fit one of the 11 categories above.

==========================================================
PHASE 2 — GRAPH CONSTRUCTION FROM EXTRACTED NER
==========================================================
Using ONLY the entities produced in Phase 1, build a community-oriented knowledge graph.

STRICT GROUNDING RULES (MOST IMPORTANT):
- Every node MUST be one of the entities extracted during Phase 1. No exceptions.
- Every edge MUST correspond to a relationship that is directly stated or unambiguously supported by the document text. Do NOT rely on prior/background real-world knowledge.
- Relationship labels must describe what the text actually says, not assumed or typical relationships between such entities in the real world.
- If you are uncertain whether a relationship is supported by the text, OMIT it.
- If the documents do not contain enough connected entities to reach the suggested node/edge counts, return FEWER nodes and edges rather than padding with invented ones. Faithfulness to the source overrides target counts.

FORMAT RULES:
1. Output ONLY valid JSON, no markdown, no comments, no preamble.
2. Use the entity name itself as the node "id", exactly as it appears in the source documents (e.g., "LockBit", "SVR", "Ukraine").
3. The node "type" field MUST be one of the lowercase tags from this fixed set, mapped from the Phase 1 categories:
   - "person"   (PERSON)
   - "org"      (ORG)
   - "gpe"      (GPE)
   - "loc"      (LOC)
   - "date"     (DATE)
   - "money"    (MONEY)
   - "event"    (EVENT)
   - "product"  (PRODUCT)
   - "norp"     (NORP)
   - "law"      (LAW)
   - "fac"      (FAC)
   No other type values are permitted.
4. Aim for 8–12 nodes and 10–18 edges ONLY IF the source material supports it. Every node MUST have at least 2 edges; otherwise drop it. Prioritise the most central entities; omit isolated nodes to keep the graph sparse but meaningful. Keep node labels and relationship strings concise (under 30 characters).
5. Assign each node a "community" integer (0-based). Nodes in the same community share a dominant theme, actor group, campaign, incident, or storyline as evidenced by the documents. Aim for 4–10 distinct communities, but only as many as the data genuinely supports.
6. The JSON must have EXACTLY this structure:
{
  "nodes": [
    {"id": "EntityName", "label": "EntityName", "type": "person|org|gpe|loc|date|money|event|product|norp|law|fac", "community": 0}
  ],
  "edges": [
    {"source": "EntityName1", "target": "EntityName2", "relationship": "string", "weight": 0.8}
  ]
}
7. "source" and "target" in edges MUST match node "id" values exactly.
8. "weight" reflects relationship strength (0.1–1.0) based on how explicitly and frequently the relationship is described in the documents: use higher weights for edges within the same community and for relationships stated multiple times or in strong terms.
9. Do NOT include any other top-level keys. Do NOT emit the Phase 1 NER list separately — it is an internal step; only the final graph JSON is returned.
"""

INSIGHTS_GRAPH_SCHEMA = """{
  "nodes": [
    {"id": "EntityName", "label": "EntityName", "type": "person|org|gpe|loc|date|money|event|product|norp|law|fac", "community": 0}
  ],
  "edges": [
    {"source": "EntityName1", "target": "EntityName2", "relationship": "string", "weight": 0.8}
  ]
}"""

INSIGHTS_GRAPH_RULES = """Rules (read INSIGHTS_GRAPH_PROMPT for full NER+graph instructions):
- Extract named entities (people, orgs, locations, events, products, dates…) from the corpus.
- Build a community knowledge graph: nodes = entities, edges = relationships stated in the text.
- 8–12 nodes, 10–18 edges (only if the corpus supports it — do not pad with invented data).
- Every node must have at least 2 edges. Every edge must match a relationship from the text.
- "source" and "target" must match node "id" values exactly.
- Assign community integers (0-based) grouping nodes that share a theme/actor/storyline.
- Do NOT add any keys beyond nodes and edges.
- Keep node labels and relationship strings short (under 30 characters each)."""

# Aliases for the new granular task naming convention
INSIGHTS_RELATIONSHIP_NETWORK_SCHEMA = INSIGHTS_GRAPH_SCHEMA
INSIGHTS_RELATIONSHIP_NETWORK_RULES = INSIGHTS_GRAPH_RULES

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

ENRICH_TRANSLATION_PROMPT = """Translate the text below into natural, fluent Romanian suitable for intelligence analysts.

Rules:
1. Output ONLY valid JSON with exactly this structure: {"text": "translation here"}
2. Produce a complete, accurate translation — do NOT summarize or omit any content.
3. Preserve proper nouns (names, organizations, locations) in their original form.
4. Keep technical terms, acronyms, and codenames unchanged.
5. If the source text is already in Romanian, return it verbatim in the "text" field.
6. Do NOT add explanations, notes, or any text outside the JSON."""

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
        return messages, "You are a professional Romanian translator. Translate accurately and completely. Output ONLY valid JSON."

    # ── Chat prompt ─────────────────────────────────────────────────────────────

    def build_chat_messages(
        self,
        user_query: str,
        chunks: list[dict],
        history: list[dict],
    ) -> tuple[list[dict], str]:
        context_block = self._format_chunks(chunks)
        n = len(chunks)
        context_header = (
            f"=== {n} RELEVANT DOCUMENT{'S' if n != 1 else ''} (ranked by relevance) ===\n"
            f"{context_block}\n"
            f"=== END OF CONTEXT ==="
        ) if n > 0 else "<context>No relevant documents found for this query.</context>"

        messages: list[dict] = []
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        user_content = f"{context_header}\n\nQuestion: {user_query}"
        messages.append({"role": "user", "content": user_content})

        return messages, RAG_SYSTEM_PROMPT

    # ── Insights prompt ─────────────────────────────────────────────────────────

    # def build_insights_messages(self, sample_docs: list[dict], task_type: str = "summary") -> tuple[list[dict], str]:
    #     """Build the messages list for the insights generation call.
    #
    #     Packs as many documents as possible into the configured context window,
    #     sending full document text for each one rather than tiny snippets.
    #
    #     Budget calculation
    #     ------------------
    #     available_chars = LLM_INSIGHTS_CTX × LLM_CHARS_PER_TOKEN
    #                       − LLM_INSIGHTS_RESERVE_CHARS
    #
    #     Documents are packed greedily in sample order: each document gets its
    #     full text up to the remaining budget. When the budget is exhausted the
    #     loop stops, so later documents are silently dropped rather than all
    #     documents getting tiny truncated snippets.
    #
    #     For a 64 k-token context (≈ 224 k chars) and an 10 k-char reserve:
    #       · ~214 k chars available for document content
    #       · A 500-char doc → ~428 full-text documents fit
    #       · A 2 000-char doc → ~107 full-text documents fit
    #     Either way this is dramatically better than 40 docs × 120-char snippets.
    #     """
    #     prompt_map = {
    #         "summary": INSIGHTS_SUMMARY_PROMPT,
    #         "graph":   INSIGHTS_GRAPH_PROMPT,
    #     }
    #     system_prompt = prompt_map.get(task_type, INSIGHTS_SUMMARY_PROMPT)
    #
    #     # ── Budget ─────────────────────────────────────────────────────────────
    #     total_ctx_chars = int(Config.LLM_INSIGHTS_CTX * Config.LLM_CHARS_PER_TOKEN)
    #     available_chars = total_ctx_chars - Config.LLM_INSIGHTS_RESERVE_CHARS
    #
    #     doc_lines   = []
    #     used_chars  = 0
    #
    #     for doc in sample_docs:
    #         title     = (doc.get("title") or "").strip()[:120]
    #         topic     = (doc.get("topic")  or "").strip()
    #         sentiment = (doc.get("sentiment") or "").strip()
    #         text      = (doc.get("text") or "").strip()
    #
    #         # Fixed metadata portion (always included)
    #         meta_parts: list[str] = []
    #         if title:     meta_parts.append(f"title={title!r}")
    #         if topic:     meta_parts.append(f"topic={topic!r}")
    #         if sentiment: meta_parts.append(f"sentiment={sentiment!r}")
    #
    #         meta_str   = ", ".join(meta_parts)
    #         # Estimate chars consumed by this doc before adding text
    #         overhead   = len(meta_str) + 6   # "[", "]", ", text=''", newline
    #
    #         remaining_for_text = available_chars - used_chars - overhead
    #         if remaining_for_text <= 0:
    #             break   # No budget left for even the metadata of this doc
    #
    #         # Pack as much text as fits
    #         if text and remaining_for_text > 40:
    #             if len(text) <= remaining_for_text:
    #                 meta_parts.append(f"text={text!r}")
    #             else:
    #                 # Truncate text to fit; mark truncation with ellipsis
    #                 trimmed = text[:remaining_for_text - 1].rstrip()
    #                 meta_parts.append(f"text={trimmed!r}…")
    #
    #         line = f"[{', '.join(meta_parts)}]"
    #         doc_lines.append(line)
    #         used_chars += len(line) + 1   # +1 for the trailing newline
    #
    #     n = len(doc_lines)
    #     approx_tokens = int(used_chars / Config.LLM_CHARS_PER_TOKEN)
    #     total_words = sum(len(doc.get("text", "").split()) for doc in sample_docs)
    #
    #     logger.info(
    #         f"[insights] {task_type}: packed {n}/{len(sample_docs)} docs "
    #         f"({used_chars:,} chars ≈ {approx_tokens:,} tokens, {total_words:,} words) "
    #         f"into {Config.LLM_INSIGHTS_CTX:,}-token context"
    #     )
    #
    #     # Select the schema + rules that go AFTER the corpus
    #     if task_type == "graph":
    #         schema = INSIGHTS_GRAPH_SCHEMA
    #         rules  = INSIGHTS_GRAPH_RULES
    #     else:
    #         schema = INSIGHTS_SUMMARY_SCHEMA
    #         rules  = INSIGHTS_SUMMARY_RULES
    #
    #     doc_block = "\n".join(doc_lines)
    #
    #     # ── Corpus-first layout ────────────────────────────────────────────────
    #     # The schema appears AFTER the documents so the model's last instruction
    #     # before generating is the output format — not a schema it read hundreds
    #     # of documents ago and has since forgotten.
    #     content = (
    #         f"=== INTELLIGENCE CORPUS ({n} documents) ===\n"
    #         f"{doc_block}\n"
    #         f"=== END CORPUS ===\n\n"
    #         f"Analyse the {n} documents above and extract structured intelligence.\n\n"
    #         f"{rules}\n\n"
    #         f"Output ONLY the following JSON structure — no extra keys, no explanation, "
    #         f"no markdown fences. Start immediately with '{{':\n"
    #         f"{schema}"
    #     )
    #
    #     messages = [{"role": "user", "content": content}]
    #     system   = (
    #         "You are a specialized intelligence extraction engine. "
    #         "Output ONLY valid JSON that exactly matches the requested schema. "
    #         "Do not output any text before or after the JSON object."
    #     )
    #     return messages, system

    def build_insights_messages(self, sample_docs: list[dict], task_type: str = "hot_topics_sentiment") -> tuple[list[dict], str]:
        """Build the messages list for the granular insights generation calls."""

        # ── Map Task Types to Schemas/Rules ──────────────────────────────────
        task_config = {
            "trending_signals":      (INSIGHTS_TRENDING_SIGNALS_SCHEMA, INSIGHTS_TRENDING_SIGNALS_RULES),
            "active_narratives":     (INSIGHTS_ACTIVE_NARRATIVES_SCHEMA, INSIGHTS_ACTIVE_NARRATIVES_RULES),
            "hot_topics_sentiment":  (INSIGHTS_HOT_TOPICS_SENTIMENT_SCHEMA, INSIGHTS_HOT_TOPICS_SENTIMENT_RULES),
            "relationship_network":  (INSIGHTS_RELATIONSHIP_NETWORK_SCHEMA, INSIGHTS_RELATIONSHIP_NETWORK_RULES),
        }

        # Compatibility fallback for old names
        if task_type == "summary": task_type = "hot_topics_sentiment"
        if task_type == "graph":   task_type = "relationship_network"

        schema, rules = task_config.get(task_type, (INSIGHTS_HOT_TOPICS_SENTIMENT_SCHEMA, INSIGHTS_HOT_TOPICS_SENTIMENT_RULES))

        # ── Budget ─────────────────────────────────────────────────────────────
        total_window_tokens = Config.LLM_INSIGHTS_CTX
        RESPONSE_RESERVE_TOKENS = 8000

        # Hard cap from config keeps prefill time manageable on small models.
        # Default 8 500 tokens ≈ 29 750 chars:
        #   simple tasks (1 500 char reserve)     → ~20 docs → consistent 20-28 s
        #   relationship_network (10 000 reserve) → ~14 docs → consistent 28-35 s
        # Values below ~7 000 trigger Ollama KV-cache eviction bimodal spikes (26s/53s).
        input_budget_tokens = min(
            Config.LLM_INSIGHTS_INPUT_MAX_TOKENS,
            total_window_tokens - RESPONSE_RESERVE_TOKENS,
        )

        total_input_chars = int(input_budget_tokens * Config.LLM_CHARS_PER_TOKEN)

        # relationship_network has a very large NER+graph prompt (~10k chars).
        # All other tasks have minimal schema+rules overhead (~1.5k chars).
        PROMPT_OVERHEAD_CHARS = {
            "relationship_network": 10000,
            "hot_topics_sentiment": 1500,
            "trending_signals":     1500,
            "active_narratives":    1500,
        }
        prompt_overhead = PROMPT_OVERHEAD_CHARS.get(task_type, Config.LLM_INSIGHTS_RESERVE_CHARS)
        available_chars = total_input_chars - prompt_overhead

        doc_lines = []
        used_chars = 0

        for doc in sample_docs:
            title = (doc.get("title") or "").strip()[:120]
            topic = (doc.get("topic") or "").strip()
            sentiment = (doc.get("sentiment") or "").strip()
            text = (doc.get("text") or "").strip()

            meta_parts: list[str] = []
            if title:     meta_parts.append(f"title={title!r}")
            if topic:     meta_parts.append(f"topic={topic!r}")
            if sentiment: meta_parts.append(f"sentiment={sentiment!r}")

            meta_str = ", ".join(meta_parts)
            overhead = len(meta_str) + 12
            remaining_for_text = available_chars - used_chars - overhead

            if remaining_for_text < 60:
                break

            if text:
                if len(text) <= remaining_for_text:
                    meta_parts.append(f"text={text!r}")
                else:
                    trimmed = text[:remaining_for_text - 5].rstrip()
                    meta_parts.append(f"text={trimmed!r}...")

            line = f"[{', '.join(meta_parts)}]"
            doc_lines.append(line)
            used_chars += len(line) + 1

        n = len(doc_lines)
        approx_tokens = int(used_chars / Config.LLM_CHARS_PER_TOKEN)
        total_words = sum(len(doc.get("text", "").split()) for doc in sample_docs[:n])

        logger.info(
            f"[insights] {task_type}: packed {n}/{len(sample_docs)} docs "
            f"({used_chars:,} chars ≈ {approx_tokens:,} tokens, {total_words:,} words) "
            f"leaving ~{RESPONSE_RESERVE_TOKENS} tokens for response."
        )

        doc_block = "\n".join(doc_lines)
        content = (
            f"=== INTELLIGENCE CORPUS ({n} documents) ===\n"
            f"{doc_block}\n"
            f"=== END CORPUS ===\n\n"
            f"Analyse the {n} documents above and extract structured intelligence.\n\n"
            f"{rules}\n\n"
            f"Output ONLY the following JSON structure — no extra keys, no explanation, "
            f"no markdown fences. Start immediately with '{{':\n"
            f"{schema}"
        )

        messages = [{"role": "user", "content": content}]
        system = (
            "You are a specialized intelligence extraction engine. "
            "Output ONLY valid JSON that exactly matches the requested schema. "
            "Do not output any text before or after the JSON object."
        )
        return messages, system


    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_chunks(chunks: list[dict]) -> str:
        """Render retrieved chunks as XML blocks for the LLM prompt.

        Each <doc> tag carries all available metadata as attributes so the model
        can write informative citations (title, date, classification, sentiment).
        Scores are already normalised to [0,1] by _filter_chunks; 1.0 = best match.
        """
        if not chunks:
            return "<context>No relevant documents found.</context>"

        parts = []
        for i, chunk in enumerate(chunks, 1):
            doc_id = chunk.get("id", "unknown")
            score  = chunk.get("score", 0)
            text   = (chunk.get("text") or "").strip()
            meta   = chunk.get("metadata") or {}

            title          = chunk.get("title") or meta.get("title") or meta.get("topic") or ""
            date           = (meta.get("date") or meta.get("created_at")
                              or meta.get("published_at") or meta.get("timestamp") or "")
            classification = meta.get("classification") or ""
            sentiment      = meta.get("sentiment") or ""

            attrs = [f'id="{doc_id}"', f'rank="{i}"', f'relevance="{score:.2f}"']
            if title:          attrs.append(f'title="{title}"')
            if date:           attrs.append(f'date="{str(date)[:10]}"')
            if classification: attrs.append(f'class="{classification}"')
            if sentiment:      attrs.append(f'sentiment="{sentiment}"')

            parts.append(f'<doc {" ".join(attrs)}>\n{text}\n</doc>')
        return "\n\n".join(parts)
