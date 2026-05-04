"""LLM-driven column→field mapping refinement.

One LLM call per file (when no profile matches). Inputs: handler name,
column list, sample records. Output: mapping refinement that may correct or
strengthen the heuristic produced by the handler.

Falls back to the heuristic mapping silently on any LLM failure — ingestion
is never blocked on the LLM here.
"""
from __future__ import annotations

import json
from typing import Optional

from framework.commons.logger import logger


_SYSTEM_PROMPT = """You are a data-mapping assistant. Given a list of column
names and a few sample rows from a tabular file, decide which column should
populate each canonical document field for our intelligence platform.

Canonical fields (use these exact keys):
  text        — the primary searchable body. REQUIRED. Pick the longest free-
                text column; if none stands out, pick the field most likely
                to be a description/body/message.
  title       — a short identifying label, if any.
  created_at  — a timestamp / date column, if any.
  author      — who wrote/created the record.
  url         — a hyperlink column, if any.

Output JSON ONLY in this exact shape (omit a key entirely if no column fits):
{
  "mapping": {
    "text":       "<column-name or null>",
    "title":      "<column-name or null>",
    "created_at": "<column-name or null>",
    "author":     "<column-name or null>",
    "url":        "<column-name or null>"
  },
  "confidence": <number 0..1>,
  "rationale":  "<one short sentence>"
}

Rules:
- The value for each key MUST be one of the column names provided, or null.
- DO NOT invent column names.
- If you can't decide, pick the closest match and lower the confidence.
"""


def _build_user_prompt(handler_name: str, columns: list[str],
                       samples: list[dict]) -> str:
    """Render a compact user prompt — column list + 5 sample rows truncated.

    Each sample value is truncated to 200 chars so a row with one huge cell
    doesn't dominate the prompt. Total prompt stays under ~2K tokens which
    fits comfortably in any context window.
    """
    cleaned_samples = []
    for s in samples[:5]:
        cleaned_samples.append({
            k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
            for k, v in (s or {}).items()
        })
    return (
        f"Handler: {handler_name}\n"
        f"Columns: {json.dumps(columns)}\n"
        f"Sample rows ({len(cleaned_samples)}):\n"
        + json.dumps(cleaned_samples, ensure_ascii=False, indent=2)
    )


def refine_mapping(handler_name: str, columns: list[str], samples: list[dict],
                   heuristic: dict) -> dict:
    """Ask the LLM for a mapping; merge with the heuristic as a safety net.

    Returns a dict like::

        {"mapping": {...}, "confidence": 0.9, "rationale": "...", "source": "llm"|"heuristic"}

    If the LLM call fails, the heuristic mapping is returned with
    ``source="heuristic"`` and ``confidence`` carried through. Callers
    treat a heuristic-source mapping the same as an LLM-source one for
    UI / state-machine purposes; the field is informational.
    """
    if not columns:
        return {"mapping": heuristic, "confidence": 0.0,
                "rationale": "no columns", "source": "heuristic"}

    try:
        from src.llm.client import get_llm
        llm = get_llm()
        user_msg = _build_user_prompt(handler_name, columns, samples)
        raw = llm.complete_json(
            messages=[{"role": "user", "content": user_msg}],
            system=_SYSTEM_PROMPT,
        )
        data = _parse_json(raw)
        if not data:
            raise ValueError(f"LLM returned non-JSON: {raw[:200]!r}")

        proposed = data.get("mapping") or {}
        # Validate every value is either None or a known column.
        cleaned = {}
        for k, v in proposed.items():
            if v is None or v == "":
                continue
            if v in columns:
                cleaned[k] = v
            else:
                logger.warning(f"[ingest-map] LLM proposed unknown column {v!r} for {k}; dropping")

        # Always carry forward at least a text mapping — fall back to
        # heuristic if the LLM dropped it.
        if not cleaned.get("text"):
            cleaned["text"] = heuristic.get("text")

        return {
            "mapping": cleaned,
            "confidence": float(data.get("confidence") or 0.7),
            "rationale": str(data.get("rationale") or ""),
            "source": "llm",
        }
    except Exception as e:
        logger.warning(f"[ingest-map] LLM refinement failed; using heuristic: {e}")
        return {
            "mapping": heuristic,
            "confidence": 0.5,
            "rationale": "LLM unavailable; using heuristic mapping.",
            "source": "heuristic",
        }


def _parse_json(s: str) -> Optional[dict]:
    """Lenient JSON parse — handles models that wrap output in ```json fences.
    Mirrors ``InsightsEngine._parse_json`` semantics."""
    if not s:
        return None
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None
