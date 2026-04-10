"""HTTP endpoint handlers for the QSINT RAG API.

All functions follow the QF Framework pattern:
    handler(app, operation, request, **kwargs) -> (body, status_code)

SSE streaming endpoints return a Flask Response object directly.
"""
import json
import re
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timezone

from flask import request as flask_request, Response, stream_with_context

from framework.commons.logger import logger
from framework.tracing import get_tracer

from src.config import Config

tracer = get_tracer()
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
from src.rag.retriever import get_retriever
from src.rag.llm_client import get_llm
from src.rag.prompt_builder import PromptBuilder
from src.rag.insights_engine import get_insights_engine


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _json():
    return flask_request.get_json(force=True, silent=True) or {}


def _cors_headers():
    """Basic CORS headers for local dev (tighten in production)."""
    return {
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    }


# ── IOC extraction ─────────────────────────────────────────────────────────────

_RE_IP       = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b')
_RE_URL      = re.compile(r'https?://[^\s<>"\'{}|\\^`\[\]]+', re.IGNORECASE)
_RE_EMAIL    = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,7}\b')
_RE_MD5      = re.compile(r'\b[a-fA-F0-9]{32}\b')
_RE_SHA1     = re.compile(r'\b[a-fA-F0-9]{40}\b')
_RE_SHA256   = re.compile(r'\b[a-fA-F0-9]{64}\b')
_RE_CVE      = re.compile(r'\bCVE-\d{4}-\d{4,7}\b', re.IGNORECASE)
_RE_PATH     = re.compile(r'(?:/(?:etc|var|home|tmp|usr|bin|sbin|opt|root|proc|sys|data|log)[/\w.\-]*|[A-Za-z]:\\[^\s<>"\']+)')
_RE_HASHTAG  = re.compile(r'#[\w\u0400-\u04FF\u0600-\u06FF]{2,}')
_RE_DOMAIN   = re.compile(
    r'\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|gov|mil|edu|info|biz|onion'
    r'|ru|cn|de|uk|fr|nl|xyz|app|cloud|online|site|tech|int|us|ca|au|jp|kr|br|in|pl|se|no|dk|fi)\b',
    re.IGNORECASE,
)


def _extract_iocs(text: str) -> dict:
    """Regex-based Indicator of Compromise extraction — no LLM required."""
    urls  = list(set(_RE_URL.findall(text)))
    clean = _RE_URL.sub(' ', text)          # avoid double-matching domains inside URLs
    hashes = list(set(_RE_MD5.findall(text) + _RE_SHA1.findall(text) + _RE_SHA256.findall(text)))
    return {
        "ips":        list(set(_RE_IP.findall(text))),
        "domains":    [d for d in set(_RE_DOMAIN.findall(clean)) if len(d) > 4],
        "urls":       urls,
        "emails":     list(set(_RE_EMAIL.findall(text))),
        "hashes":     hashes,
        "cves":       list(set(_RE_CVE.findall(text))),
        "file_paths": list(set(_RE_PATH.findall(text))),
        "hashtags":   list(set(_RE_HASHTAG.findall(text))),
    }


def _geocode_location(name: str) -> dict | None:
    """Geocode a place name via Nominatim (OpenStreetMap). Returns None on failure."""
    try:
        params = urllib.parse.urlencode({"q": name, "format": "json", "limit": 1})
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{params}",
            headers={"User-Agent": "QSINT-RAG-Intelligence-Platform/1.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            results = json.loads(resp.read().decode())
        if results:
            return {
                "name":         name,
                "lat":          float(results[0]["lat"]),
                "lon":          float(results[0]["lon"]),
                "display_name": results[0].get("display_name", name),
            }
    except Exception as e:
        logger.warning(f"[geocode] '{name}': {e}")
    return None


# ── Health ─────────────────────────────────────────────────────────────────────

def health_check(app, operation, request, **kwargs):
    """GET /health — full dependency health check."""
    with tracer.start_as_current_span("api.health_check") as span:
        retriever = get_retriever()
        ds_status = retriever.get_status()

        llm_ok = True
        try:
            get_llm()
        except Exception:
            llm_ok = False

        ok = ds_status.get("error") is None and llm_ok
        span.set_attribute("health.ok", ok)
        span.set_attribute("health.datasource_type", ds_status.get("type", "unknown"))
        span.set_attribute("health.llm_model", Config.LLM_MODEL)

        body = {
            "status":     "ok" if ok else "degraded",
            "datasource": ds_status,
            "llm":        {"model": Config.LLM_MODEL, "ok": llm_ok},
        }
        return body, (200 if ok else 503)


def liveness(app, operation, request, **kwargs):
    """GET /liveness — lightweight Kubernetes liveness probe."""
    return {"alive": True}, 200


# ── Chat helpers ───────────────────────────────────────────────────────────────

def _filter_chunks(chunks: list[dict]) -> list[dict]:
    """Apply dynamic score threshold to retrieved chunks.

    Strategy:
    1. Drop any chunk whose score is below RAG_SCORE_THRESHOLD.
    2. If ALL chunks are below the threshold (e.g. very poor retrieval), keep
       the top RAG_MAX_CONTEXT_CHUNKS as a fallback so the LLM always has
       something to work with.
    3. Cap the final set at RAG_MAX_CONTEXT_CHUNKS.
    """
    threshold = Config.RAG_SCORE_THRESHOLD
    max_k     = Config.RAG_MAX_CONTEXT_CHUNKS

    if not chunks:
        return []

    filtered = [c for c in chunks if (c.get("score") or 0) >= threshold]

    # Fallback: if filtering removed everything, keep the best ones anyway
    if not filtered:
        filtered = sorted(chunks, key=lambda c: c.get("score", 0), reverse=True)

    return filtered[:max_k]


def _format_sources(chunks: list[dict], datasource: str) -> list[dict]:
    """Serialise retrieved chunks to the sources list stored with each message.

    Returns full doc id, score, short text preview, datasource, and title so
    the frontend can build a "Go To Document" link.
    """
    return [
        {
            "id":         c.get("id", ""),
            "score":      round(c.get("score", 0), 4),
            "text":       (c.get("text") or "")[:300],
            "title":      c.get("title") or c.get("source") or "",
            "datasource": datasource,
        }
        for c in chunks
    ]


# ── Chat (sync) ────────────────────────────────────────────────────────────────

def chat_handler(app, operation, request, **kwargs):
    """POST /v1/chat — blocking RAG chat (no streaming).

    Body: { "message": str, "session_id"?: str }
    Returns: { "session_id", "message_id", "content", "sources" }
    """
    with tracer.start_as_current_span("api.chat") as span:
        body       = _json()
        user_query = (body.get("message") or "").strip()
        if not user_query:
            return {"error": "message is required"}, 400

        session_id = body.get("session_id")

        # Create session if not provided
        if not session_id:
            datasource = body.get("datasource", "default")
            session    = create_session(datasource=datasource)
            session_id = session["id"]
        else:
            session = get_session(session_id)
            if not session:
                return {"error": f"Session {session_id} not found"}, 404

        datasource = session.get("datasource", "default")

        span.set_attribute("chat.session_id", session_id)
        span.set_attribute("chat.query_length", len(user_query))
        span.set_attribute("chat.datasource", datasource)

        # Persist user message
        append_message(session_id, "user", user_query)

        # Retrieve context and apply dynamic score threshold
        retriever    = get_retriever()
        raw_chunks   = retriever.retrieve(user_query, Config.RAG_TOP_K, index_name=datasource)
        chunks       = _filter_chunks(raw_chunks)
        span.set_attribute("chat.chunks_retrieved", len(raw_chunks))
        span.set_attribute("chat.chunks_used", len(chunks))

        # Load conversation history
        history = get_recent_messages(session_id, Config.HISTORY_TURNS)
        history = [m for m in history if not (m["role"] == "user" and m["content"] == user_query)]

        # Build prompt and call LLM
        builder  = PromptBuilder()
        messages, system = builder.build_chat_messages(user_query, chunks, history)
        llm      = get_llm()

        try:
            answer = llm.complete(messages, system)
            span.set_attribute("chat.answer_length", len(answer))
        except Exception as e:
            logger.error(f"[chat] LLM error: {e}", exc_info=True)
            span.set_attribute("chat.error", str(e))
            return {"error": f"LLM error: {str(e)}"}, 500

        # Persist assistant answer — store full id, score, and short preview
        sources  = _format_sources(chunks, datasource)
        msg_dict = append_message(session_id, "assistant", answer, sources=sources)

        return {
            "session_id": session_id,
            "message_id": msg_dict["id"],
            "content":    answer,
            "sources":    sources,
        }, 200


# ── Chat (SSE streaming) ────────────────────────────────────────────────────────

def chat_stream_handler(app, operation, request, **kwargs):
    """POST /v1/chat/stream — SSE streaming RAG chat.

    Body: { "message": str, "session_id"?: str }

    SSE event format:
      data: {"type": "delta",   "content": "..."}
      data: {"type": "sources", "sources": [...]}
      data: {"type": "done",    "message_id": "...", "session_id": "..."}
      data: {"type": "error",   "content": "..."}
    """
    body       = _json()
    user_query = (body.get("message") or "").strip()
    if not user_query:
        def _err():
            yield f'data: {json.dumps({"type": "error", "content": "message is required"})}\n\n'
        return Response(stream_with_context(_err()), mimetype="text/event-stream",
                        headers=_cors_headers())

    session_id = body.get("session_id")

    # Create or validate session before streaming starts
    if not session_id:
        datasource = body.get("datasource", "default")
        session    = create_session(datasource=datasource)
        session_id = session["id"]
    else:
        session = get_session(session_id)
        if not session:
            def _err():
                yield f'data: {json.dumps({"type": "error", "content": f"Session {session_id} not found"})}\n\n'
            return Response(stream_with_context(_err()), mimetype="text/event-stream",
                            headers=_cors_headers())

    datasource = session.get("datasource", "default")

    # Pre-flight: retrieve + history traced before the streaming generator starts
    with tracer.start_as_current_span("api.chat_stream.preflight") as span:
        span.set_attribute("chat.session_id", session_id)
        span.set_attribute("chat.query_length", len(user_query))
        span.set_attribute("chat.datasource", datasource)

        append_message(session_id, "user", user_query)

        retriever  = get_retriever()
        raw_chunks = retriever.retrieve(user_query, Config.RAG_TOP_K, index_name=datasource)
        chunks     = _filter_chunks(raw_chunks)
        span.set_attribute("chat.chunks_retrieved", len(raw_chunks))
        span.set_attribute("chat.chunks_used", len(chunks))

        history = get_recent_messages(session_id, Config.HISTORY_TURNS)
        history = [m for m in history if not (m["role"] == "user" and m["content"] == user_query)]

        builder  = PromptBuilder()
        messages, system = builder.build_chat_messages(user_query, chunks, history)
        sources  = _format_sources(chunks, datasource)

    def generate():
        """Generator yielding SSE events while streaming from the LLM.

        A child span wraps the full LLM stream so token latency is visible in Jaeger.
        """
        with tracer.start_as_current_span("api.chat_stream.llm") as llm_span:
            llm_span.set_attribute("chat.session_id", session_id)
            llm_span.set_attribute("llm.model", Config.LLM_MODEL)

            llm = get_llm()
            accumulated = []
            delta_count = 0

            yield f'data: {json.dumps({"type": "sources", "sources": sources, "session_id": session_id})}\n\n'

            try:
                for delta in llm.stream(messages, system):
                    accumulated.append(delta)
                    delta_count += 1
                    yield f'data: {json.dumps({"type": "delta", "content": delta})}\n\n'

                full_answer = "".join(accumulated)
                llm_span.set_attribute("chat.answer_length", len(full_answer))
                llm_span.set_attribute("chat.delta_count", delta_count)

                msg = append_message(session_id, "assistant", full_answer, sources=sources)
                yield f'data: {json.dumps({"type": "done", "message_id": msg["id"], "session_id": session_id})}\n\n'

            except Exception as e:
                logger.error(f"[chat_stream] Error: {e}", exc_info=True)
                llm_span.set_attribute("chat.error", str(e))
                yield f'data: {json.dumps({"type": "error", "content": str(e)})}\n\n'

    headers = {
        **_cors_headers(),
        "Cache-Control":     "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers=headers,
    )


# ── Insights ────────────────────────────────────────────────────────────────────

def insights_handler(app, operation, request, **kwargs):
    """GET /v1/insights — return (possibly cached) intelligence report.

    Query params:
      datasource  str  default "default"
    """
    datasource = flask_request.args.get("datasource", "default")
    with tracer.start_as_current_span("api.insights.get") as span:
        span.set_attribute("insights.datasource", datasource)
        try:
            engine   = get_insights_engine()
            insights = engine.get_insights(datasource=datasource)
            span.set_attribute("insights.cached", insights.get("_meta", {}).get("cached", False))
            return insights, 200
        except Exception as e:
            logger.error(f"[insights] Error: {e}", exc_info=True)
            span.set_attribute("insights.error", str(e))
            return {"error": str(e)}, 500


def insights_refresh_handler(app, operation, request, **kwargs):
    """POST /v1/insights/refresh — force regeneration of the intelligence report."""
    body       = _json()
    datasource = body.get("datasource", "default")
    with tracer.start_as_current_span("api.insights.refresh") as span:
        span.set_attribute("insights.datasource", datasource)
        try:
            engine   = get_insights_engine()
            insights = engine.get_insights(datasource=datasource, force_refresh=True)
            return insights, 200
        except Exception as e:
            logger.error(f"[insights] Refresh error: {e}", exc_info=True)
            span.set_attribute("insights.error", str(e))
            return {"error": str(e)}, 500


def insights_delete_handler(app, operation, request, **kwargs):
    """DELETE /v1/insights — wipe the insights cache for a datasource."""
    datasource = flask_request.args.get("datasource", "default")
    with tracer.start_as_current_span("api.insights.delete") as span:
        span.set_attribute("insights.datasource", datasource)
        try:
            engine = get_insights_engine()
            engine.invalidate(datasource)
            return {"status": "deleted", "datasource": datasource}, 200
        except Exception as e:
            logger.error(f"[insights] Delete error: {e}", exc_info=True)
            span.set_attribute("insights.error", str(e))
            return {"error": str(e)}, 500


# ── Sessions ────────────────────────────────────────────────────────────────────

def sessions_handler(app, operation, request, **kwargs):
    """GET  /v1/sessions — list sessions.
    POST /v1/sessions — create a new session.
    """
    with tracer.start_as_current_span("api.sessions.list_or_create") as span:
        span.set_attribute("http.method", flask_request.method)
        if flask_request.method == "POST":
            body       = _json()
            datasource = body.get("datasource", "default")
            title      = body.get("title")
            session    = create_session(title=title, datasource=datasource)
            span.set_attribute("session.id", session["id"])
            return session, 201

        # GET
        datasource = flask_request.args.get("datasource")
        limit      = int(flask_request.args.get("limit", 50))
        sessions   = list_sessions(datasource=datasource, limit=limit)
        span.set_attribute("sessions.count", len(sessions))
        return {"sessions": sessions, "total": len(sessions)}, 200


def session_detail_handler(app, operation, request, **kwargs):
    """GET    /v1/sessions/<session_id>
    DELETE /v1/sessions/<session_id>
    PATCH  /v1/sessions/<session_id>   — rename
    """
    session_id = kwargs.get("session_id") or flask_request.view_args.get("session_id")
    with tracer.start_as_current_span("api.sessions.detail") as span:
        span.set_attribute("session.id", session_id or "")
        span.set_attribute("http.method", flask_request.method)

        if flask_request.method == "DELETE":
            found = delete_session(session_id)
            span.set_attribute("session.found", bool(found))
            return ({} if found else {"error": "Not found"}), (200 if found else 404)

        if flask_request.method == "PATCH":
            body  = _json()
            title = body.get("title")
            if not title:
                return {"error": "title is required"}, 400
            updated = update_session_title(session_id, title)
            span.set_attribute("session.found", bool(updated))
            return (updated or {"error": "Not found"}), (200 if updated else 404)

        # GET
        session = get_session(session_id)
        if not session:
            span.set_attribute("session.found", False)
            return {"error": "Not found"}, 404
        span.set_attribute("session.found", True)
        return session, 200


def session_messages_handler(app, operation, request, **kwargs):
    """GET /v1/sessions/<session_id>/messages — return all messages in a session."""
    session_id = kwargs.get("session_id") or flask_request.view_args.get("session_id")
    with tracer.start_as_current_span("api.sessions.messages") as span:
        span.set_attribute("session.id", session_id or "")
        if not get_session(session_id):
            return {"error": "Session not found"}, 404
        messages = get_messages(session_id)
        span.set_attribute("messages.count", len(messages))
        return {"messages": messages, "total": len(messages)}, 200


# ── Datasource status ───────────────────────────────────────────────────────────

def datasource_status_handler(app, operation, request, **kwargs):
    """GET /v1/datasource/status — return connectivity info for the active datasource."""
    datasource = flask_request.args.get("datasource")
    with tracer.start_as_current_span("api.datasource.status") as span:
        retriever = get_retriever()
        status    = retriever.get_status(index_name=datasource)
        span.set_attribute("datasource.type", status.get("type", "unknown"))
        span.set_attribute("datasource.error", str(status.get("error", "")))
        return status, 200

def datasource_indices_handler(app, operation, request, **kwargs):
    """GET /v1/datasource/indices — return a list of available indices."""
    with tracer.start_as_current_span("api.datasource.indices") as span:
        try:
            from src.datasource.es_client import ESClient
            client = ESClient()
            indices = client.list_indices()
            return {"indices": indices}, 200
        except Exception as e:
            logger.error(f"[api] Error fetching indices: {e}")
            return {"error": str(e)}, 500

def documents_handler(app, operation, request, **kwargs):
    """GET /v1/documents — get raw documents for tabular view.

    Optional filter params:
      filter_sentiment    — match on sentiment.keyword field in ES
      filter_status       — 'in_progress' | 'done' — resolved from PG
      filter_labels       — comma-separated label values — resolved from PG
      filter_classification — match on enrichment classification field in PG
    """
    datasource = flask_request.args.get("datasource")
    query      = flask_request.args.get("query", "")
    offset     = int(flask_request.args.get("offset", 0))
    limit      = int(flask_request.args.get("limit", 50))

    filter_sentiment      = flask_request.args.get("filter_sentiment", "").strip() or None
    filter_status         = flask_request.args.get("filter_status", "").strip() or None
    filter_labels_raw     = flask_request.args.get("filter_labels", "").strip()
    filter_classification = flask_request.args.get("filter_classification", "").strip() or None

    filter_labels = [l.strip() for l in filter_labels_raw.split(",") if l.strip()] if filter_labels_raw else []

    with tracer.start_as_current_span("api.documents") as span:
        span.set_attribute("documents.datasource", datasource or "")
        try:
            from src.datasource.es_client import ESClient
            from src.session.models import DocumentStatus, DocumentLabel, DocumentEnrichment, get_db

            # Resolve PG-based filters to a set of matching doc IDs
            id_filter = None  # None means "no restriction"

            if filter_status or filter_labels or filter_classification:
                id_sets = []

                if filter_status:
                    with get_db() as db:
                        rows = db.query(DocumentStatus.doc_id).filter_by(
                            datasource=datasource, status=filter_status
                        ).all()
                    id_sets.append({r.doc_id for r in rows})

                if filter_labels:
                    # A document must have ALL requested labels.
                    # Build result dict inside the session to avoid DetachedInstanceError.
                    with get_db() as db:
                        rows = db.query(DocumentLabel).filter_by(datasource=datasource).all()
                        rows_data = [(r.doc_id, list(r.labels or [])) for r in rows]
                    matching = set()
                    for doc_id_r, lbls in rows_data:
                        row_labels = set(lbls)
                        if all(lbl in row_labels for lbl in filter_labels):
                            matching.add(doc_id_r)
                    id_sets.append(matching)

                if filter_classification:
                    fc_lower = filter_classification.lower()
                    # Build (doc_id, classification) pairs inside the session.
                    with get_db() as db:
                        enriched_rows = db.query(DocumentEnrichment).filter(
                            DocumentEnrichment.datasource == datasource,
                            DocumentEnrichment.status == "complete",
                        ).all()
                        enriched_data = [(e.doc_id, (e.payload or {}).get("classification", "") or "") for e in enriched_rows]
                    matching = {doc_id_e for doc_id_e, cls in enriched_data if fc_lower in cls.lower()}
                    id_sets.append(matching)

                # Intersect all PG filter sets
                if id_sets:
                    combined = id_sets[0]
                    for s in id_sets[1:]:
                        combined = combined & s
                    id_filter = list(combined)

            client = ESClient()
            docs, total = client.get_documents(
                index_name=datasource,
                offset=offset,
                limit=limit,
                query=query,
                id_filter=id_filter,
                sentiment_filter=filter_sentiment,
            )
            span.set_attribute("documents.total", total)
            return {"documents": docs, "total": total}, 200
        except Exception as e:
            logger.error(f"[api] Error fetching documents: {e}")
            return {"error": str(e)}, 500

def documents_enriched_handler(app, operation, request, **kwargs):
    """GET /v1/documents/enriched — return doc_ids that have complete enrichment.

    Query params: datasource (required)
    Returns: { "doc_ids": ["id1", "id2", ...] }
    """
    from src.session.models import DocumentEnrichment, get_db
    datasource = flask_request.args.get("datasource")
    if not datasource:
        return {"error": "datasource is required"}, 400

    try:
        with get_db() as db:
            rows = db.query(DocumentEnrichment.doc_id).filter(
                DocumentEnrichment.datasource == datasource,
                DocumentEnrichment.status == "complete",
            ).all()
        return {"doc_ids": [r.doc_id for r in rows]}, 200
    except Exception as e:
        logger.error(f"[api] documents_enriched_handler error: {e}")
        return {"error": str(e)}, 500


def _run_enrichment_background(datasource: str, doc_id: str, text: str) -> None:
    """Background worker: run full document enrichment and persist result.

    Called via ThreadPoolExecutor so the HTTP thread never blocks on LLM calls.
    """
    from src.session.models import DocumentEnrichment, get_db
    from src.rag.llm_client import get_llm
    from src.rag.prompt_builder import PromptBuilder
    from src.rag.insights_engine import InsightsEngine

    # Mark as processing and record started_at
    try:
        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if row:
                row.status = "processing"
                row.started_at = datetime.now(timezone.utc)
                db.commit()
    except Exception as e:
        logger.error(f"[enrich] DB pre-update failed: {e}")
        return

    try:
        builder = PromptBuilder()
        llm = get_llm()

        # ── Step 1: Main LLM enrichment (all structured fields) ──────────────
        messages, system = builder.build_enrichment_messages(text[:3000])
        raw = llm.complete_json(messages, system)
        logger.debug(f"[enrich] raw LLM output (first 500): {raw[:500]!r}")
        payload = InsightsEngine._parse_json(raw)
        if payload is None:
            logger.error(f"[enrich] unparseable JSON for doc_id={doc_id}: {raw[:300]!r}")
            raise ValueError("Failed to parse enrichment JSON from LLM")

        # Guard: the model sometimes returns a template/ready response instead of
        # enrichment (e.g. when thinking is suppressed). Fail fast so we don't waste
        # time on geocoding/translation with a garbage payload.
        _EXPECTED = {"summary", "sentiment", "classification", "entities"}
        if not any(k in payload for k in _EXPECTED):
            logger.error(f"[enrich] LLM returned non-enrichment JSON keys={list(payload.keys())} doc_id={doc_id}")
            raise ValueError(f"LLM did not enrich the document (got keys: {list(payload.keys())})")

        # ── Step 2: IOC extraction (regex, synchronous) ───────────────────────
        payload["iocs"] = _extract_iocs(text)

        # ── Step 3: Geocode extracted location names via Nominatim ────────────
        location_names = payload.pop("locations", []) or []
        if isinstance(location_names, list):
            geocoded = []
            for loc in location_names[:12]:
                if isinstance(loc, str) and loc.strip():
                    result = _geocode_location(loc.strip())
                    if result:
                        geocoded.append(result)
            payload["locations"] = geocoded

        # ── Step 4: Translation (if document is not in Romanian) ─────────────
        doc_lang = (payload.get("language") or "en").lower()
        if doc_lang not in ("ro", "ron", "rum"):
            try:
                t_msgs, t_sys = builder.build_translation_messages(text[:3000])
                t_raw = llm.complete_json(t_msgs, t_sys)
                t_data = InsightsEngine._parse_json(t_raw)
                if t_data and t_data.get("text"):
                    payload["translation"] = t_data["text"]  # store plain string
            except Exception as te:
                logger.warning(f"[enrich] Translation failed for doc_id={doc_id}: {te}")

        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if row:
                row.status = "complete"
                row.payload = payload
                row.error = None
                db.commit()
                logger.info(f"[enrich] Complete: doc_id={doc_id}", "magenta")
    except Exception as e:
        logger.error(f"[enrich] Failed doc_id={doc_id}: {e}", exc_info=True)
        try:
            with get_db() as db:
                row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                if row:
                    row.status = "error"
                    row.error = str(e)
                    db.commit()
        except Exception as db_err:
            logger.error(f"[enrich] DB error-update failed: {db_err}")


def document_enrich_stream_handler(app, operation, request, **kwargs):
    """POST /v1/documents/enrich/stream — SSE stream of enrichment steps.

    Body: { "datasource": str, "doc_id": str, "text": str, "force"?: bool }

    SSE event format:
      data: {"type": "cached",   "payload": {...}}          — already complete, no work done
      data: {"type": "partial",  "payload": {...so far...}} — a step finished
      data: {"type": "complete", "payload": {...full...}}   — all steps done, persisted to DB
      data: {"type": "error",    "error": "..."}            — enrichment failed
    """
    body      = _json()
    datasource = body.get("datasource")
    doc_id     = body.get("doc_id")
    text       = body.get("text", "")
    force      = bool(body.get("force", False))

    sse_headers = {
        **_cors_headers(),
        "Cache-Control":     "no-cache",
        "X-Accel-Buffering": "no",
    }

    if not datasource or not doc_id or not text:
        def _err():
            yield f'data: {json.dumps({"type": "error", "error": "datasource, doc_id, and text are required"})}\n\n'
        return Response(stream_with_context(_err()), mimetype="text/event-stream", headers=sse_headers)

    logger.info(f"[enrich] ▶ stream started doc_id={doc_id} ds={datasource} force={force}", "green")

    def generate():
        from src.session.models import DocumentEnrichment, get_db
        from src.rag.llm_client import get_llm
        from src.rag.prompt_builder import PromptBuilder
        from src.rag.insights_engine import InsightsEngine

        # ── Check cache (read-only — no status writes yet) ───────────────────
        try:
            with get_db() as db:
                row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                if row and row.status == "complete" and not force:
                    logger.info(f"[enrich] ✓ cache hit  doc_id={doc_id} ds={datasource}", "green")
                    yield f'data: {json.dumps({"type": "cached", "payload": row.payload or {}})}\n\n'
                    return
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "error": f"DB error: {e}"})}\n\n'
            return

        # ── Run enrichment inline (no intermediate DB status writes) ─────────
        # The SSE path is a live HTTP connection — we only persist on completion.
        # Intermediate pending/processing rows from the stream show up as phantom
        # tasks in the task monitor and make it look like more are running than are.
        accumulated: dict = {}
        builder = PromptBuilder()
        llm = get_llm()
        t0 = datetime.now(timezone.utc)

        try:
            # ── Step 1: Main LLM (summary + all structured fields) ───────────
            # Write "processing" to DB only here — the LLM call is imminent.
            # This is the one DB write before completion so the task monitor shows
            # exactly the docs that are actively using the GPU, not every open tab.
            now = datetime.now(timezone.utc)
            try:
                with get_db() as db:
                    row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                    if not row:
                        row = DocumentEnrichment(doc_id=doc_id, datasource=datasource,
                                                 generated_at=now, started_at=now,
                                                 status="processing")
                        db.add(row)
                    else:
                        row.status     = "processing"
                        row.started_at = now
                        row.error      = None
                    db.commit()
            except Exception:
                pass  # non-fatal — enrichment continues even if status write fails

            messages, system = builder.build_enrichment_messages(text[:3000])
            raw = llm.complete_json(messages, system)
            logger.debug(f"[enrich_stream] raw LLM output (first 500): {raw[:500]!r}")
            step1 = InsightsEngine._parse_json(raw)
            if step1 is None:
                logger.error(f"[enrich_stream] unparseable raw (full): {raw!r}")
                raise ValueError("LLM returned unparseable JSON for main enrichment")
            accumulated.update(step1)
            yield f'data: {json.dumps({"type": "partial", "payload": dict(accumulated)})}\n\n'

            # ── Step 2: IOC extraction (regex, instant) ───────────────────────
            accumulated["iocs"] = _extract_iocs(text)
            yield f'data: {json.dumps({"type": "partial", "payload": dict(accumulated)})}\n\n'

            # ── Step 3: Geocode location names ───────────────────────────────
            location_names = accumulated.pop("locations", []) or []
            if isinstance(location_names, list):
                geocoded = []
                for loc in location_names[:12]:
                    if isinstance(loc, str) and loc.strip():
                        result = _geocode_location(loc.strip())
                        if result:
                            geocoded.append(result)
                accumulated["locations"] = geocoded
            yield f'data: {json.dumps({"type": "partial", "payload": dict(accumulated)})}\n\n'

            # ── Step 4: Translation ───────────────────────────────────────────
            doc_lang = (accumulated.get("language") or "en").lower()
            if doc_lang not in ("ro", "ron", "rum"):
                try:
                    t_msgs, t_sys = builder.build_translation_messages(text[:3000])
                    t_raw = llm.complete_json(t_msgs, t_sys)
                    t_data = InsightsEngine._parse_json(t_raw)
                    if t_data and t_data.get("text"):
                        accumulated["translation"] = t_data["text"]
                except Exception as te:
                    logger.warning(f"[enrich_stream] Translation failed: {te}")
            yield f'data: {json.dumps({"type": "partial", "payload": dict(accumulated)})}\n\n'

            # ── Persist as complete (first and only DB write for this path) ───
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            now = datetime.now(timezone.utc)
            try:
                with get_db() as db:
                    row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                    if not row:
                        row = DocumentEnrichment(doc_id=doc_id, datasource=datasource,
                                                 generated_at=now, started_at=now)
                        db.add(row)
                    row.status    = "complete"
                    row.payload   = dict(accumulated)
                    row.error     = None
                    row.updated_at = now
                    db.commit()
            except Exception as dbe:
                logger.error(f"[enrich_stream] DB persist failed doc_id={doc_id}: {dbe}")

            logger.info(f"[enrich] ✓ complete doc_id={doc_id} ds={datasource} elapsed={elapsed:.1f}s", "magenta")
            yield f'data: {json.dumps({"type": "complete", "payload": dict(accumulated)})}\n\n'

        except Exception as e:
            logger.error(f"[enrich_stream] Failed doc_id={doc_id}: {e}", exc_info=True)
            yield f'data: {json.dumps({"type": "error", "error": str(e)})}\n\n'

    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=sse_headers)


def document_enrichment_handler(app, operation, request, **kwargs):
    """POST /v1/documents/enrich — start async enrichment or return cached result.

    Body: { "datasource": str, "doc_id": str, "text": str, "force"?: bool }
    Returns: DocumentEnrichment row dict.
    - 200 if already complete (and force=False)
    - 202 if pending/processing or just started
    - 400 on bad input
    """
    body = _json()
    datasource = body.get("datasource")
    doc_id = body.get("doc_id")
    text = body.get("text", "")
    force = bool(body.get("force", False))

    if not datasource or not doc_id or not text:
        return {"error": "datasource, doc_id, and text are required"}, 400

    with tracer.start_as_current_span("api.documents.enrich") as span:
        span.set_attribute("enrich.doc_id", doc_id)
        span.set_attribute("enrich.datasource", datasource)
        span.set_attribute("enrich.force", force)

        from src.session.models import DocumentEnrichment, get_db

        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()

            # Return cached complete result unless force-reload requested
            if row and row.status == "complete" and not force:
                span.set_attribute("enrich.cache_hit", True)
                return row.to_dict(), 200

            # Return current in-progress state (don't double-submit)
            if row and row.status in ("pending", "processing") and not force:
                return row.to_dict(), 202

            # Create or reset the row and trigger background work
            if not row:
                row = DocumentEnrichment(doc_id=doc_id, datasource=datasource, status="pending")
                db.add(row)
            else:
                row.status = "pending"
                row.error = None
                if force:
                    row.payload = None
            db.commit()
            result = row.to_dict()

        from src.worker.kafka_producer import publish_task
        publish_task({"task_type": "enrich_doc", "datasource": datasource, "doc_id": doc_id, "text": text})
        span.set_attribute("enrich.cache_hit", False)
        return result, 202


def document_enrich_field_handler(app, operation, request, **kwargs):
    """POST /v1/documents/enrich/field — reload a single enrichment field.

    Body: { "datasource": str, "doc_id": str, "text": str, "field": str }
    Supported fields: sentiment, classification, entities, summary.
    Returns the updated DocumentEnrichment row dict.
    """
    body = _json()
    datasource = body.get("datasource")
    doc_id = body.get("doc_id")
    text = body.get("text", "")
    field = body.get("field", "")

    # iocs uses regex only; locations/timeline/graph/translation use LLM (or LLM+geo)
    VALID_FIELDS = {
        "sentiment", "classification", "entities", "summary",
        "graph", "timeline", "locations", "iocs", "translation",
    }
    if not datasource or not doc_id or not text or field not in VALID_FIELDS:
        return {"error": f"datasource, doc_id, text, and field ({'/'.join(sorted(VALID_FIELDS))}) are required"}, 400

    with tracer.start_as_current_span("api.documents.enrich.field") as span:
        span.set_attribute("enrich.doc_id", doc_id)
        span.set_attribute("enrich.field", field)

        from src.session.models import DocumentEnrichment, get_db

        # Mark the field as refreshing (keep existing payload)
        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if not row:
                row = DocumentEnrichment(doc_id=doc_id, datasource=datasource, status="processing")
                db.add(row)
            db.commit()
            result = row.to_dict()

        from src.worker.kafka_producer import publish_task
        publish_task({"task_type": "enrich_field", "datasource": datasource,
                      "doc_id": doc_id, "text": text, "field": field})
        return result, 202

def insights_stream_handler(app, operation, request, **kwargs):
    """GET /v1/insights/stream — SSE stream that pushes task-status events.

    The client receives:
      data: {"type": "state",       "tasks": {...},   "datasource": str}  — initial snapshot
      data: {"type": "task_update", "insight_type": str, "task": {...}}   — per-task update
      : heartbeat                                                          — every 25 s
    """
    datasource = flask_request.args.get("datasource", "default")

    from src.rag.insights_engine import get_insights_engine, _event_bus

    def generate():
        engine = get_insights_engine()

        # Send current state immediately so the client doesn't wait
        current = engine._load_all_from_cache(datasource)
        yield f'data: {json.dumps({"type": "state", "tasks": current, "datasource": datasource})}\n\n'

        # Subscribe for future updates
        q = _event_bus.subscribe(datasource)
        try:
            while True:
                try:
                    event = q.get(timeout=25)
                    yield f'data: {json.dumps(event)}\n\n'
                except Exception:
                    # Timeout — send SSE keepalive comment
                    yield ": heartbeat\n\n"
        finally:
            _event_bus.unsubscribe(datasource, q)

    headers = {
        **_cors_headers(),
        "Cache-Control":     "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=headers)


def dashboard_task_restart_handler(app, operation, request, **kwargs):
    """POST /v1/dashboard/tasks/restart — restart an insights or enrichment task.

    Body: {
        "task_category": "insight" | "enrichment",
        "datasource": str,
        "task": str   -- insight_type (e.g., "summary") or doc_id for enrichments
    }
    """
    body = _json()
    category = body.get("task_category", "insight")
    datasource = body.get("datasource")
    task = body.get("task")

    if not datasource or not task:
        return {"error": "datasource and task are required"}, 400

    with tracer.start_as_current_span("api.dashboard.tasks.restart") as span:
        span.set_attribute("task.category", category)
        span.set_attribute("task.datasource", datasource)
        span.set_attribute("task.id", task)

        try:
            if category == "insight":
                from src.rag.insights_engine import get_insights_engine
                engine = get_insights_engine()

                # Mark pending and publish coordinator task
                engine._set_task_status(datasource, task, "pending", "manual_restart", clear_data=True)
                from src.worker.kafka_producer import publish_task
                publish_task({"task_type": "insight_coordinator", "datasource": datasource})
                return {"status": "restarted", "task": task, "category": category}, 200

            elif category == "enrichment":
                # doc_id == task; fetch text from ES and re-run enrichment
                from src.datasource.es_client import ESClient
                from src.session.models import DocumentEnrichment, get_db

                client = ESClient()
                docs, _ = client.get_documents(index_name=datasource, offset=0, limit=1,
                                               id_filter=[task])
                text = ""
                if docs:
                    text = docs[0].get("text", "")

                if not text:
                    return {"error": "Document text not found for enrichment restart"}, 404

                with get_db() as db:
                    row = db.query(DocumentEnrichment).filter_by(doc_id=task, datasource=datasource).first()
                    if row:
                        row.status = "pending"
                        row.error = None
                        row.payload = None
                        db.commit()

                from src.worker.kafka_producer import publish_task
                publish_task({"task_type": "enrich_doc", "datasource": datasource,
                              "doc_id": task, "text": text})
                return {"status": "restarted", "task": task, "category": category}, 200
            else:
                return {"error": f"Unknown task_category: {category}"}, 400

        except Exception as e:
            logger.error(f"[api] Task restart failed: {e}", exc_info=True)
            return {"error": str(e)}, 500


def dashboard_task_clear_handler(app, operation, request, **kwargs):
    """DELETE /v1/dashboard/tasks — clear (delete) a specific task record.

    Query params: task_category, datasource, task (insight_type or doc_id)
    """
    category = flask_request.args.get("task_category", "insight")
    datasource = flask_request.args.get("datasource")
    task = flask_request.args.get("task")

    if not datasource or not task:
        return {"error": "datasource and task are required"}, 400

    with tracer.start_as_current_span("api.dashboard.tasks.clear") as span:
        span.set_attribute("task.category", category)
        span.set_attribute("task.datasource", datasource)

        try:
            from src.session.models import InsightsCache, DocumentEnrichment, get_db

            with get_db() as db:
                if category == "insight":
                    db.query(InsightsCache).filter(
                        InsightsCache.datasource == datasource,
                        InsightsCache.insight_type == task,
                    ).delete()
                elif category == "enrichment":
                    db.query(DocumentEnrichment).filter(
                        DocumentEnrichment.datasource == datasource,
                        DocumentEnrichment.doc_id == task,
                    ).delete()
                db.commit()

            return {"status": "deleted", "task": task, "category": category}, 200
        except Exception as e:
            logger.error(f"[api] Task clear failed: {e}", exc_info=True)
            return {"error": str(e)}, 500


def task_refresh_handler(app, operation, request, **kwargs):
    """POST /v1/insights/task/refresh — refresh a single failed task."""
    body = _json()
    datasource = body.get("datasource")
    task = body.get("task")
    
    if not datasource or not task:
        return {"error": "datasource and task are required"}, 400
        
    with tracer.start_as_current_span("api.insights.task.refresh") as span:
        try:
            from src.rag.insights_engine import get_insights_engine
            engine = get_insights_engine()
            current = engine._load_all_from_cache(datasource)
            sample_hash = "manual_refresh"
            if current and task in current:
                sample_hash = current[task].get("sample_hash", "manual_refresh")

            from src.rag.retriever import get_retriever
            import hashlib
            retriever = get_retriever()
            sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS, index_name=datasource)
            if sample:
                doc_ids = sorted([str(d.get("id")) for d in sample])
                sample_hash = hashlib.sha256(",".join(doc_ids).encode()).hexdigest()

            engine._set_task_status(datasource, task, "pending", sample_hash, clear_data=True)

            from src.worker.kafka_producer import publish_task
            if task == "stats":
                publish_task({"task_type": "insight_stats", "datasource": datasource,
                              "sample_hash": sample_hash})
            else:
                publish_task({"task_type": "insight_ai", "datasource": datasource,
                              "insight_type": task, "sample_hash": sample_hash})

            return {"status": "restarted", "task": task}, 200
        except Exception as e:
            return {"error": str(e)}, 500

def dashboard_tasks_handler(app, operation, request, **kwargs):
    """GET /v1/dashboard/tasks — get platform-wide task status."""
    with tracer.start_as_current_span("api.dashboard.tasks") as span:
        try:
            from src.rag.insights_engine import get_insights_engine
            engine = get_insights_engine()
            data = engine.get_all_tasks()
            return data, 200
        except Exception as e:
            logger.error(f"[api] Error fetching dashboard tasks: {e}")
            return {"error": str(e)}, 500


def tasks_list_handler(app, operation, request, **kwargs):
    """GET /v1/tasks — unified, filterable, paginated task list.

    Query params:
        status       : pending | processing | complete | error  (default: all)
        category     : insight | enrichment                     (default: all)
        datasource   : string                                   (default: all)
        task_type    : string (insight_type or "enrichment")    (default: all)
        sort         : field:dir  e.g. updated_at:desc          (default: updated_at:desc)
        page         : int                                      (default: 1)
        size         : int  1-200                               (default: 50)
        created_after  : ISO timestamp
        created_before : ISO timestamp
    """
    from datetime import datetime, timezone
    from src.session.models import InsightsCache, DocumentEnrichment, get_db

    status_f     = flask_request.args.get("status", "")
    category_f   = flask_request.args.get("category", "")
    datasource_f = flask_request.args.get("datasource", "")
    task_type_f  = flask_request.args.get("task_type", "")
    sort_raw     = flask_request.args.get("sort", "updated_at:desc")
    page         = max(1, int(flask_request.args.get("page", 1)))
    size         = min(200, max(1, int(flask_request.args.get("size", 50))))
    created_after_s  = flask_request.args.get("created_after", "")
    created_before_s = flask_request.args.get("created_before", "")

    # Parse sort param
    SORTABLE = {"updated_at", "generated_at", "started_at", "status", "retry_count", "datasource"}
    sort_field, sort_dir = "updated_at", "desc"
    if ":" in sort_raw:
        sf, sd = sort_raw.split(":", 1)
        if sf in SORTABLE:
            sort_field = sf
            sort_dir = "asc" if sd == "asc" else "desc"

    def _ts(s):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    created_after  = _ts(created_after_s)
    created_before = _ts(created_before_s)

    with tracer.start_as_current_span("api.tasks.list"):
        try:
            tasks = []

            with get_db() as db:
                # ── Insight tasks ────────────────────────────────────────────
                if not category_f or category_f == "insight":
                    q = db.query(InsightsCache)
                    if status_f:
                        q = q.filter(InsightsCache.status == status_f)
                    if datasource_f:
                        q = q.filter(InsightsCache.datasource == datasource_f)
                    if task_type_f and task_type_f != "enrichment":
                        q = q.filter(InsightsCache.insight_type == task_type_f)
                    if created_after:
                        q = q.filter(InsightsCache.generated_at >= created_after)
                    if created_before:
                        q = q.filter(InsightsCache.generated_at <= created_before)

                    for row in q.all():
                        tasks.append({
                            "id":          f"insight__{row.datasource}__{row.insight_type}",
                            "category":    "insight",
                            "task_type":   row.insight_type,
                            "datasource":  row.datasource,
                            "doc_id":      None,
                            "status":      row.status,
                            "retry_count": row.retry_count,
                            "error":       row.error,
                            "has_output":  bool(row.payload),
                            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                            "started_at":   row.started_at.isoformat()   if row.started_at   else None,
                            "updated_at":   (row.updated_at or row.generated_at).isoformat(),
                            "sample_hash":  row.sample_hash,
                        })

                # ── Enrichment tasks ─────────────────────────────────────────
                if not category_f or category_f == "enrichment":
                    q = db.query(DocumentEnrichment)
                    if status_f:
                        q = q.filter(DocumentEnrichment.status == status_f)
                    if datasource_f:
                        q = q.filter(DocumentEnrichment.datasource == datasource_f)
                    if task_type_f and task_type_f not in ("", "enrichment"):
                        pass  # enrichment tasks don't have sub-types to filter by
                    if created_after:
                        q = q.filter(DocumentEnrichment.generated_at >= created_after)
                    if created_before:
                        q = q.filter(DocumentEnrichment.generated_at <= created_before)

                    for row in q.all():
                        tasks.append({
                            "id":          f"enrichment__{row.datasource}__{row.doc_id}",
                            "category":    "enrichment",
                            "task_type":   "enrichment",
                            "datasource":  row.datasource,
                            "doc_id":      row.doc_id,
                            "status":      row.status,
                            "retry_count": row.retry_count,
                            "error":       row.error,
                            "has_output":  bool(row.payload),
                            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                            "started_at":   row.started_at.isoformat()   if row.started_at   else None,
                            "updated_at":   (row.updated_at or row.generated_at).isoformat(),
                        })

            # ── Sort ─────────────────────────────────────────────────────────
            def _sort_key(t):
                v = t.get(sort_field) or ""
                return v

            tasks.sort(key=_sort_key, reverse=(sort_dir == "desc"))

            # ── Stats (computed pre-slice) ────────────────────────────────────
            total = len(tasks)
            stats = {
                "total":      total,
                "pending":    sum(1 for t in tasks if t["status"] == "pending"),
                "processing": sum(1 for t in tasks if t["status"] == "processing"),
                "complete":   sum(1 for t in tasks if t["status"] == "complete"),
                "error":      sum(1 for t in tasks if t["status"] == "error"),
                "insights":   sum(1 for t in tasks if t["category"] == "insight"),
                "enrichments":sum(1 for t in tasks if t["category"] == "enrichment"),
            }

            # ── Paginate ──────────────────────────────────────────────────────
            offset = (page - 1) * size
            page_items = tasks[offset: offset + size]

            return {
                "tasks":  page_items,
                "total":  total,
                "page":   page,
                "size":   size,
                "stats":  stats,
            }, 200

        except Exception as e:
            logger.error(f"[api] tasks_list_handler error: {e}", exc_info=True)
            return {"error": str(e)}, 500


def task_detail_handler(app, operation, request, task_id: str = "", **kwargs):
    """GET /v1/tasks/<task_id> — single task detail by synthetic id.

    task_id format: insight__{datasource}__{insight_type}
                    enrichment__{datasource}__{doc_id}
    """
    from src.session.models import InsightsCache, DocumentEnrichment, get_db

    parts = task_id.split("__", 2)
    if len(parts) != 3:
        return {"error": "Invalid task_id format"}, 400

    category, datasource, key = parts

    with tracer.start_as_current_span("api.tasks.detail"):
        try:
            with get_db() as db:
                if category == "insight":
                    row = db.query(InsightsCache).filter_by(
                        datasource=datasource, insight_type=key
                    ).first()
                    if not row:
                        return {"error": "Task not found"}, 404
                    return {
                        "id":          task_id,
                        "category":    "insight",
                        "task_type":   row.insight_type,
                        "datasource":  row.datasource,
                        "doc_id":      None,
                        "status":      row.status,
                        "retry_count": row.retry_count,
                        "error":       row.error,
                        "payload":     row.payload,
                        "has_output":  bool(row.payload),
                        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                        "started_at":   row.started_at.isoformat()   if row.started_at   else None,
                        "updated_at":   (row.updated_at or row.generated_at).isoformat(),
                        "sample_hash":  row.sample_hash,
                    }, 200

                elif category == "enrichment":
                    row = db.query(DocumentEnrichment).filter_by(
                        datasource=datasource, doc_id=key
                    ).first()
                    if not row:
                        return {"error": "Task not found"}, 404
                    return {
                        "id":          task_id,
                        "category":    "enrichment",
                        "task_type":   "enrichment",
                        "datasource":  row.datasource,
                        "doc_id":      row.doc_id,
                        "status":      row.status,
                        "retry_count": row.retry_count,
                        "error":       row.error,
                        "payload":     row.payload,
                        "has_output":  bool(row.payload),
                        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                        "started_at":   row.started_at.isoformat()   if row.started_at   else None,
                        "updated_at":   (row.updated_at or row.generated_at).isoformat(),
                    }, 200
                else:
                    return {"error": "Unknown category"}, 400

        except Exception as e:
            logger.error(f"[api] task_detail_handler error: {e}", exc_info=True)
            return {"error": str(e)}, 500


def tasks_analytics_handler(app, operation, request, **kwargs):
    """GET /v1/tasks/analytics — aggregated timing and throughput stats.

    Query params:
        datasource : filter to one datasource (optional)
        category   : insight | enrichment (optional)

    Returns:
        timing     : avg queue_time_ms, avg exec_time_ms, avg total_time_ms per category+type
        throughput : task counts bucketed by completed_at into 5m/1h/12h/1d/7d windows
        status_dist: counts by status
        type_dist  : counts by task_type
    """
    from src.session.models import InsightsCache, DocumentEnrichment, get_db

    datasource_f = flask_request.args.get("datasource", "")
    category_f   = flask_request.args.get("category", "")

    now_utc = datetime.now(timezone.utc)

    try:
        with get_db() as db:
            # ── Collect all tasks (insight + enrichment) into dicts ──────────────
            rows = []

            if not category_f or category_f == "insight":
                q = db.query(InsightsCache)
                if datasource_f:
                    q = q.filter(InsightsCache.datasource == datasource_f)
                for row in q.all():
                    rows.append({
                        "category":     "insight",
                        "task_type":    row.insight_type,
                        "status":       row.status,
                        "generated_at": row.generated_at,
                        "started_at":   row.started_at,
                        "updated_at":   row.updated_at or row.generated_at,
                    })

            if not category_f or category_f == "enrichment":
                q = db.query(DocumentEnrichment)
                if datasource_f:
                    q = q.filter(DocumentEnrichment.datasource == datasource_f)
                for row in q.all():
                    rows.append({
                        "category":     "enrichment",
                        "task_type":    "enrichment",
                        "status":       row.status,
                        "generated_at": row.generated_at,
                        "started_at":   row.started_at,
                        "updated_at":   row.updated_at or row.generated_at,
                    })

        # ── Timing stats (only for tasks with started_at) ──────────────────────
        timing_buckets: dict = {}  # key=(category,task_type) → lists of ms values
        for r in rows:
            if not r["started_at"] or not r["generated_at"]:
                continue
            gen = r["generated_at"]
            start = r["started_at"]
            upd   = r["updated_at"]
            if gen.tzinfo is None:
                gen = gen.replace(tzinfo=timezone.utc)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if upd and upd.tzinfo is None:
                upd = upd.replace(tzinfo=timezone.utc)

            queue_ms = int((start - gen).total_seconds() * 1000)
            exec_ms  = int((upd - start).total_seconds() * 1000) if upd and r["status"] in ("complete", "error") else None
            total_ms = int((upd - gen).total_seconds() * 1000) if upd and r["status"] in ("complete", "error") else None

            key = (r["category"], r["task_type"])
            if key not in timing_buckets:
                timing_buckets[key] = {"queue": [], "exec": [], "total": []}
            if queue_ms >= 0:
                timing_buckets[key]["queue"].append(queue_ms)
            if exec_ms is not None and exec_ms >= 0:
                timing_buckets[key]["exec"].append(exec_ms)
            if total_ms is not None and total_ms >= 0:
                timing_buckets[key]["total"].append(total_ms)

        def _avg(lst):
            return round(sum(lst) / len(lst)) if lst else None

        timing = []
        for (cat, ttype), data in timing_buckets.items():
            timing.append({
                "category":      cat,
                "task_type":     ttype,
                "avg_queue_ms":  _avg(data["queue"]),
                "avg_exec_ms":   _avg(data["exec"]),
                "avg_total_ms":  _avg(data["total"]),
                "sample_count":  len(data["queue"]),
            })

        # ── Throughput — tasks completed within each window ────────────────────
        windows = {
            "5m":  5   * 60,
            "1h":  1   * 3600,
            "12h": 12  * 3600,
            "1d":  24  * 3600,
            "7d":  7   * 24 * 3600,
        }
        throughput = {}
        for label, secs in windows.items():
            cutoff = now_utc.replace(tzinfo=None) - __import__("datetime").timedelta(seconds=secs)
            count = sum(
                1 for r in rows
                if r["status"] == "complete"
                and r["updated_at"]
                and (r["updated_at"].replace(tzinfo=None) if r["updated_at"].tzinfo else r["updated_at"]) >= cutoff
            )
            throughput[label] = count

        # ── Status distribution ────────────────────────────────────────────────
        status_dist: dict = {}
        for r in rows:
            status_dist[r["status"]] = status_dist.get(r["status"], 0) + 1

        # ── Type distribution ──────────────────────────────────────────────────
        type_dist: dict = {}
        for r in rows:
            k = r["task_type"]
            type_dist[k] = type_dist.get(k, 0) + 1

        # ── Time series for chart (completed tasks bucketed into 1h slots for 7d)
        from collections import defaultdict
        series: dict = defaultdict(int)
        for r in rows:
            if r["status"] == "complete" and r["updated_at"]:
                upd = r["updated_at"]
                if upd.tzinfo is None:
                    upd = upd.replace(tzinfo=timezone.utc)
                age_secs = (now_utc - upd).total_seconds()
                if age_secs <= 7 * 24 * 3600:
                    # Bucket to nearest hour
                    bucket_ts = int(upd.timestamp() // 3600 * 3600)
                    series[bucket_ts] += 1

        time_series = sorted(
            [{"ts": ts * 1000, "count": cnt} for ts, cnt in series.items()],
            key=lambda x: x["ts"],
        )

        return {
            "timing":      timing,
            "throughput":  throughput,
            "status_dist": status_dist,
            "type_dist":   type_dist,
            "time_series": time_series,
            "total_tasks": len(rows),
        }, 200

    except Exception as e:
        logger.error(f"[api] tasks_analytics_handler error: {e}", exc_info=True)
        return {"error": str(e)}, 500


def documents_status_handler(app, operation, request, **kwargs):
    """GET|POST /v1/documents/status — fetch or set analyst review status for documents.

    GET  ?datasource=x          → { "statuses": { doc_id: "in_progress"|"done" } }
    POST { datasource, doc_id, status }
         status = "in_progress" | "done" | null (null clears the status)
    """
    from src.session.models import DocumentStatus, get_db

    method = flask_request.method

    if method == "GET":
        datasource = flask_request.args.get("datasource")
        if not datasource:
            return {"error": "datasource is required"}, 400
        with get_db() as db:
            rows = db.query(DocumentStatus).filter_by(datasource=datasource).all()
            statuses = {r.doc_id: r.status for r in rows}
        return {"statuses": statuses}, 200

    # POST — upsert or clear
    body = _json()
    datasource = body.get("datasource")
    doc_id     = body.get("doc_id")
    status     = body.get("status")   # None/null means clear

    if not datasource or not doc_id:
        return {"error": "datasource and doc_id are required"}, 400
    if status is not None and status not in ("in_progress", "done"):
        return {"error": "status must be 'in_progress', 'done', or null"}, 400

    with get_db() as db:
        row = db.query(DocumentStatus).filter_by(doc_id=doc_id, datasource=datasource).first()
        if status is None:
            if row:
                db.delete(row)
        elif row:
            row.status = status
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = DocumentStatus(doc_id=doc_id, datasource=datasource, status=status)
            db.add(row)

    return {"doc_id": doc_id, "datasource": datasource, "status": status}, 200


def documents_labels_handler(app, operation, request, **kwargs):
    """GET|POST /v1/documents/labels — fetch or set analyst labels for documents.

    GET  ?datasource=x          → { "labels": { doc_id: ["label1", "label2"] } }
    POST { datasource, doc_id, labels: ["label1", "label2"] }
         Pass labels=[] to clear all labels for the document.
    """
    from src.session.models import DocumentLabel, get_db

    method = flask_request.method

    if method == "GET":
        datasource = flask_request.args.get("datasource")
        if not datasource:
            return {"error": "datasource is required"}, 400
        with get_db() as db:
            rows = db.query(DocumentLabel).filter_by(datasource=datasource).all()
            labels_map = {r.doc_id: r.labels or [] for r in rows}
        return {"labels": labels_map}, 200

    # POST — upsert
    body       = _json()
    datasource = body.get("datasource")
    doc_id     = body.get("doc_id")
    labels     = body.get("labels")

    if not datasource or not doc_id:
        return {"error": "datasource and doc_id are required"}, 400
    if not isinstance(labels, list):
        return {"error": "labels must be an array"}, 400
    # Sanitise: unique, non-empty strings, max 50 chars each
    labels = list({str(l).strip()[:50] for l in labels if str(l).strip()})

    with get_db() as db:
        row = db.query(DocumentLabel).filter_by(doc_id=doc_id, datasource=datasource).first()
        if labels:
            if row:
                row.labels     = labels
                row.updated_at = datetime.now(timezone.utc)
            else:
                row = DocumentLabel(doc_id=doc_id, datasource=datasource, labels=labels)
                db.add(row)
        else:
            # Empty list → delete the row
            if row:
                db.delete(row)

    return {"doc_id": doc_id, "datasource": datasource, "labels": labels}, 200
