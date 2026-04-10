"""HTTP endpoint handlers for the QSINT RAG API.

All functions follow the QF Framework pattern:
    handler(app, operation, request, **kwargs) -> (body, status_code)

SSE streaming endpoints return a Flask Response object directly.
"""
import json
import uuid

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

        # Retrieve context
        retriever = get_retriever()
        chunks    = retriever.retrieve(user_query, Config.RAG_TOP_K, index_name=datasource)
        span.set_attribute("chat.chunks_retrieved", len(chunks))

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

        # Persist assistant answer
        sources   = [{"id": c["id"], "score": c["score"], "text": c["text"][:200]} for c in chunks]
        msg_dict  = append_message(session_id, "assistant", answer, sources=sources)

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

        retriever = get_retriever()
        chunks    = retriever.retrieve(user_query, Config.RAG_TOP_K, index_name=datasource)
        span.set_attribute("chat.chunks_retrieved", len(chunks))

        history = get_recent_messages(session_id, Config.HISTORY_TURNS)
        history = [m for m in history if not (m["role"] == "user" and m["content"] == user_query)]

        builder  = PromptBuilder()
        messages, system = builder.build_chat_messages(user_query, chunks, history)
        sources  = [{"id": c["id"], "score": c["score"], "text": c["text"][:200]} for c in chunks]

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
    """GET /v1/documents — get raw documents for tabular view."""
    datasource = flask_request.args.get("datasource")
    query = flask_request.args.get("query", "")
    offset = int(flask_request.args.get("offset", 0))
    limit = int(flask_request.args.get("limit", 50))
    
    with tracer.start_as_current_span("api.documents") as span:
        try:
            from src.datasource.es_client import ESClient
            client = ESClient()
            docs, total = client.get_documents(index_name=datasource, offset=offset, limit=limit, query=query)
            return {"documents": docs, "total": total}, 200
        except Exception as e:
            logger.error(f"[api] Error fetching documents: {e}")
            return {"error": str(e)}, 500

def _run_enrichment_background(datasource: str, doc_id: str, text: str) -> None:
    """Background worker: run full document enrichment and persist result.

    Called via ThreadPoolExecutor so the HTTP thread never blocks on LLM calls.
    """
    from src.session.models import DocumentEnrichment, get_db
    from src.rag.llm_client import get_llm
    from src.rag.prompt_builder import PromptBuilder
    from src.rag.insights_engine import InsightsEngine

    # Mark as processing
    try:
        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if row:
                row.status = "processing"
                db.commit()
    except Exception as e:
        logger.error(f"[enrich] DB pre-update failed: {e}")
        return

    try:
        builder = PromptBuilder()
        messages, system = builder.build_enrichment_messages(text[:3000])
        llm = get_llm()
        raw = llm.complete_json(messages, system)
        payload = InsightsEngine._parse_json(raw)
        if not payload:
            raise ValueError("Failed to parse enrichment JSON from LLM")

        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if row:
                row.status = "complete"
                row.payload = payload
                row.error = None
                db.commit()
                logger.info(f"[enrich] Complete: doc_id={doc_id}")
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
        from src.rag.insights_engine import _executor

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

        _executor.submit(_run_enrichment_background, datasource, doc_id, text)
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

    VALID_FIELDS = {"sentiment", "classification", "entities", "summary"}
    if not datasource or not doc_id or not text or field not in VALID_FIELDS:
        return {"error": f"datasource, doc_id, text, and field ({'/'.join(VALID_FIELDS)}) are required"}, 400

    with tracer.start_as_current_span("api.documents.enrich.field") as span:
        span.set_attribute("enrich.doc_id", doc_id)
        span.set_attribute("enrich.field", field)

        from src.session.models import DocumentEnrichment, get_db
        from src.rag.insights_engine import _executor

        def _run_field_enrichment():
            from src.rag.llm_client import get_llm
            from src.rag.prompt_builder import PromptBuilder
            from src.rag.insights_engine import InsightsEngine

            try:
                builder = PromptBuilder()
                messages, system = builder.build_field_enrichment_messages(text[:3000], field)
                llm = get_llm()
                raw = llm.complete_json(messages, system)
                partial = InsightsEngine._parse_json(raw)
                if not partial:
                    raise ValueError(f"Failed to parse {field} JSON from LLM")

                with get_db() as db:
                    row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                    if not row:
                        row = DocumentEnrichment(doc_id=doc_id, datasource=datasource, status="complete", payload={})
                        db.add(row)
                    existing = dict(row.payload or {})
                    existing.update(partial)
                    row.payload = existing
                    row.status = "complete"
                    row.error = None
                    db.commit()
                    logger.info(f"[enrich] Field '{field}' updated for doc_id={doc_id}")
            except Exception as e:
                logger.error(f"[enrich] Field '{field}' failed: {e}", exc_info=True)
                try:
                    with get_db() as db:
                        row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                        if row:
                            row.error = str(e)
                            db.commit()
                except Exception:
                    pass

        # Mark the field as refreshing (keep existing payload)
        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if not row:
                row = DocumentEnrichment(doc_id=doc_id, datasource=datasource, status="processing")
                db.add(row)
            db.commit()
            result = row.to_dict()

        _executor.submit(_run_field_enrichment)
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
                from src.rag.insights_engine import get_insights_engine, _executor
                engine = get_insights_engine()
                from src.rag.retriever import get_retriever
                import hashlib

                # Mark pending and run coordinator to re-sample + trigger
                engine._set_task_status(datasource, task, "pending", "manual_restart", clear_data=True)
                _executor.submit(engine._run_coordinator, datasource)
                return {"status": "restarted", "task": task, "category": category}, 200

            elif category == "enrichment":
                # doc_id == task; fetch text from ES and re-run enrichment
                from src.datasource.es_client import ESClient
                from src.session.models import DocumentEnrichment, get_db
                from src.rag.insights_engine import _executor

                client = ESClient()
                docs, _ = client.get_documents(index_name=datasource, offset=0, limit=1,
                                               query=f"_id:{task}")
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

                _executor.submit(_run_enrichment_background, datasource, task, text)
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
            # Force trigger just that task by manually clearing its state and submitting
            # (We can borrow internal methods to do this)
            current = engine._load_all_from_cache(datasource)
            sample_hash = "manual_refresh"
            if current and task in current:
                sample_hash = current[task].get("sample_hash", "manual_refresh")
                
            from src.rag.retriever import get_retriever
            from src.config import Config
            import hashlib
            retriever = get_retriever()
            sample = retriever.get_sample(Config.INSIGHTS_MAX_DOCS, index_name=datasource)
            if sample:
                doc_ids = sorted([str(d.get("id")) for d in sample])
                sample_hash = hashlib.sha256(",".join(doc_ids).encode()).hexdigest()
                
            engine._set_task_status(datasource, task, "pending", sample_hash, clear_data=True)
            
            from concurrent.futures import ThreadPoolExecutor
            # Import the internal executor from insights_engine
            from src.rag.insights_engine import _executor
            if task == "stats":
                _executor.submit(engine._run_stats_task, datasource, sample_hash)
            else:
                _executor.submit(engine._run_ai_task, datasource, task, sample, sample_hash)
                
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
