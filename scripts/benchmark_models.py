#!/usr/bin/env python3
"""
benchmark_models.py — Compare multiple Ollama models for intelligence tasks.

Tests each model against:
  1. Enrichment task (single ~1k char doc) — sentinel for basic speed
  2. Insights task   (corpus-level analysis, 15 docs)
  3. Relationship network (heaviest: NER + graph, 70 docs packed to context budget)

All calls are direct to Ollama (no app stack overhead). Reports TTFT, total time,
generation speed, and JSON parse success for each model.

Usage:
    python scripts/benchmark_models.py [--index qsint_docs_europe]

Results → benchmarks/results/bench_models_<timestamp>.md  (also printed here)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from openai import OpenAI

# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_ES_HOST      = os.getenv("ES_HOST", "http://localhost:9200")
DEFAULT_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
DEFAULT_INDEX        = "qsint_docs_europe"
LLM_TIMEOUT          = 180   # per-call wall-clock limit (s)
RESULTS_DIR          = Path(__file__).parent.parent / "benchmarks" / "results"

# ── Task definitions ───────────────────────────────────────────────────────────

TASKS = {
    "enrichment": {
        "label": "Enrichment (1 doc)",
        "system": "You are a specialized JSON extraction engine. Output ONLY valid JSON.",
        "schema": '{"summary":"string","sentiment":"positive|negative|neutral|mixed|hostile","classification":"string","entities":[{"name":"string","type":"string"}]}',
        "rules":  "Extract structured intelligence from the document. Output ONLY valid JSON matching the schema.",
        "n_docs": 1,
        "doc_chars": 1200,
    },
    "hot_topics": {
        "label": "Hot Topics (15 docs)",
        "system": "You are a specialized JSON extraction engine. Output ONLY valid JSON.",
        "schema": '{"hot_topics":[{"topic":"string","sentiment_score":0.0,"sentiment_label":"positive|negative|neutral|hostile","brief_context":"string"}]}',
        "rules":  "List up to 10 discrete topics mentioned across the corpus. sentiment_score: -1.0 to 1.0.",
        "n_docs": 15,
        "doc_chars": 800,
    },
    "relationship_network": {
        "label": "Relationship Network (70 docs → packed to budget)",
        "system": "You are a specialized JSON extraction engine. Output ONLY valid JSON.",
        "schema": '{"nodes":[{"id":"string","label":"string","type":"person|org|gpe|loc|event","community":0}],"edges":[{"source":"string","target":"string","relationship":"string","weight":0.8}]}',
        "rules":  (
            "Extract Named Entities (people, orgs, countries, events) from the documents. "
            "Build a community knowledge graph. Rules: 10-20 nodes, 15-30 edges, "
            "every node needs at least 2 edges, community=0-based integer grouping. "
            "source/target must match node id exactly."
        ),
        "n_docs": 70,
        "doc_chars": 800,
    },
}

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ── Helpers ────────────────────────────────────────────────────────────────────

def list_models(base_url: str) -> list[str]:
    """List available models via the standard OpenAI GET /v1/models endpoint."""
    resp = requests.get(f"{base_url}/models", timeout=10)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]


def get_model_ctx(base_url: str, model: str) -> int:
    """Get context window for a model via GET /v1/models/{id} (SGLang exposes max_model_len)."""
    try:
        resp = requests.get(f"{base_url}/models/{model}", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        ctx = data.get("max_model_len") or data.get("context_window")
        return int(ctx) if ctx else 4096
    except Exception:
        return 4096


def fetch_docs(es_host: str, index: str, n: int) -> list[dict]:
    url = f"{es_host}/{index}/_search"
    body = {"size": n, "query": {"function_score": {"query": {"match_all": {}}, "random_score": {}}},
            "_source": ["title", "text", "topic", "sentiment"]}
    resp = requests.post(url, json=body, timeout=30)
    resp.raise_for_status()
    out = []
    for h in resp.json().get("hits", {}).get("hits", []):
        s = h["_source"]
        out.append({"title": (s.get("title") or "")[:120], "topic": s.get("topic",""),
                    "sentiment": s.get("sentiment",""), "text": (s.get("text") or "")})
    return out


def build_prompt(docs: list[dict], task: dict, max_chars: int) -> str:
    lines = []
    used = 0
    for doc in docs:
        text = (doc.get("text") or "")[:task["doc_chars"]]
        parts = []
        if doc.get("title"):     parts.append(f"title={doc['title']!r}")
        if doc.get("topic"):     parts.append(f"topic={doc['topic']!r}")
        if doc.get("sentiment"): parts.append(f"sentiment={doc['sentiment']!r}")
        if text:                 parts.append(f"text={text!r}")
        line = f"[{', '.join(parts)}]"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1

    n = len(lines)
    doc_block = "\n".join(lines)
    return (
        f"=== INTELLIGENCE CORPUS ({n} document{'s' if n > 1 else ''}) ===\n"
        f"{doc_block}\n"
        f"=== END CORPUS ===\n\n"
        f"{task['rules']}\n\n"
        f"Output ONLY the following JSON structure:\n{task['schema']}"
    ), n


def measure_ttft_and_total(client: OpenAI, model: str, messages: list[dict]) -> tuple[float, float, int, bool]:
    """Stream response to measure TTFT separately from total time."""
    t0 = time.perf_counter()
    ttft = None
    content_parts = []
    ok = True
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
            stream=True,
            timeout=LLM_TIMEOUT,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if ttft is None:
                    ttft = time.perf_counter() - t0
                content_parts.append(chunk.choices[0].delta.content)
    except Exception as e:
        ok = False
        print(f"      [ERR] {e!s:.80}")
    total = time.perf_counter() - t0
    content = THINK_RE.sub("", "".join(content_parts)).strip()
    tokens_est = len(content) // 4   # rough estimate
    return ttft or total, total, tokens_est, ok, content


def try_parse_json(text: str) -> bool:
    try:
        cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        json.loads(cleaned)
        return True
    except Exception:
        # Try brace extraction
        start = text.find("{")
        if start >= 0:
            try:
                fixed = re.sub(r",(\s*[}\]])", r"\1", text[start:])
                json.loads(fixed)
                return True
            except Exception:
                pass
    return False


def stats(values: list[float]) -> dict:
    if not values:
        return {"min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0}
    s = sorted(values)
    n = len(s)
    return {
        "min": round(min(s), 2),
        "max": round(max(s), 2),
        "avg": round(sum(s) / n, 2),
        "p50": round(s[n // 2], 2),
        "p95": round(s[min(int(n * 0.95), n - 1)], 2),
    }


# ── Main benchmark ─────────────────────────────────────────────────────────────

def benchmark_model(client: OpenAI, model: str, all_docs: dict[str, list[dict]],
                    reps: int = 3) -> dict:
    """Run all tasks against one model. Returns per-task timing data."""
    results = {}
    print(f"\n  Model: {model}")

    for task_key, task_def in TASKS.items():
        docs = all_docs[task_key]
        # Budget: reserve 2048 tokens for output (assume 4 chars/token)
        max_input_chars = 20_000   # ~5000 tokens input cap
        prompt_text, n_packed = build_prompt(docs, task_def, max_input_chars)
        messages = [
            {"role": "system", "content": task_def["system"]},
            {"role": "user",   "content": prompt_text},
        ]
        prompt_chars = len(prompt_text) + len(task_def["system"])
        prompt_tokens_est = prompt_chars // 4

        print(f"    [{task_def['label']}] {n_packed} docs packed, ~{prompt_tokens_est} input tokens")
        run_ttfts, run_totals, run_ok, run_json = [], [], [], []

        for rep in range(reps):
            print(f"      rep {rep+1}/{reps} ...", end="", flush=True)
            ttft, total, tokens_est, ok, content = measure_ttft_and_total(client, model, messages)
            json_ok = try_parse_json(content) if ok else False
            tok_s = round(tokens_est / max(total - ttft, 0.01), 1)
            run_ttfts.append(ttft)
            run_totals.append(total)
            run_ok.append(ok)
            run_json.append(json_ok)
            status = f"TTFT={ttft:.2f}s total={total:.2f}s ~{tok_s}tok/s json={'✅' if json_ok else '❌'}"
            print(f" {status}")

        results[task_key] = {
            "label":         task_def["label"],
            "n_docs":        n_packed,
            "prompt_tokens": prompt_tokens_est,
            "ttft":          stats(run_ttfts),
            "total":         stats(run_totals),
            "ok_rate":       sum(run_ok) / reps,
            "json_ok_rate":  sum(run_json) / reps,
        }
    return results


def format_report(model_results: dict[str, dict], run_ts: str, index: str) -> str:
    lines = [
        "# Multi-Model LLM Benchmark Report",
        "",
        f"**Date:** {run_ts}",
        f"**ES Index:** `{index}`",
        f"**Mode:** Direct Ollama API (streaming, TTFT measured)",
        f"**Models tested:** {', '.join(f'`{m}`' for m in model_results)}",
        "",
        "---",
        "",
    ]

    for task_key in TASKS:
        task_label = TASKS[task_key]["label"]
        lines += [
            f"## Task: {task_label}",
            "",
            "| Model | Input tokens | TTFT avg (s) | TTFT p95 (s) | Total avg (s) | Total p95 (s) | JSON ✓ |",
            "|-------|-------------|--------------|--------------|---------------|---------------|--------|",
        ]
        for model, task_data in model_results.items():
            td = task_data.get(task_key, {})
            if not td:
                lines.append(f"| {model} | N/A | N/A | N/A | N/A | N/A | — |")
                continue
            json_pct = f"{td['json_ok_rate']*100:.0f}%"
            lines.append(
                f"| `{model}` | ~{td['prompt_tokens']} | "
                f"{td['ttft']['avg']} | {td['ttft']['p95']} | "
                f"{td['total']['avg']} | {td['total']['p95']} | "
                f"{json_pct} |"
            )
        lines += ["", ""]

    # Per-model summary
    lines += [
        "---",
        "",
        "## Summary per Model",
        "",
    ]
    for model, task_data in model_results.items():
        ctx = task_data.get("_ctx", "?")
        lines += [
            f"### `{model}` (ctx={ctx})",
            "",
            "| Task | TTFT avg | Total avg | JSON ✓ |",
            "|------|----------|-----------|--------|",
        ]
        for task_key in TASKS:
            td = task_data.get(task_key, {})
            if not td:
                lines.append(f"| {TASKS[task_key]['label']} | ERR | ERR | — |")
                continue
            lines.append(
                f"| {td['label']} | {td['ttft']['avg']}s | {td['total']['avg']}s | "
                f"{td['json_ok_rate']*100:.0f}% |"
            )
        lines += ["", ""]

    lines += [
        "---",
        "",
        "## Observations",
        "",
        "- **TTFT** = Time To First Token (measures prefill latency).",
        "- **Total** = Full response time (TTFT + generation).",
        "- **JSON ✓** = Response successfully parsed as valid JSON.",
        "- Enrichment task has the shortest input (~300 tokens) → best TTFT indicator.",
        "- Relationship network has the largest output (~1500 tokens) → generation-bound.",
        "- GPU during benchmark: RTX 3080, 10GB VRAM.",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index",   default=DEFAULT_INDEX)
    parser.add_argument("--es",      default=DEFAULT_ES_HOST)
    parser.add_argument("--llm",     default=DEFAULT_LLM_BASE_URL)
    parser.add_argument("--models",  default=None,
                        help="Comma-separated model names. Default: all discovered models.")
    parser.add_argument("--reps",    default=2, type=int, help="Repetitions per task per model")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"bench_models_{ts}.md"

    print("=" * 60)
    print("Multi-Model LLM Benchmark")
    print("=" * 60)

    # Discover models
    all_models = list_models(args.llm)
    if args.models:
        models = [m.strip() for m in args.models.split(",")]
    else:
        models = all_models
    print(f"Models to test: {models}")

    # Fetch doc pools once (reuse across models)
    print(f"\nFetching docs from ES ({args.index})...")
    max_needed = max(t["n_docs"] for t in TASKS.values())
    raw_docs   = fetch_docs(args.es, args.index, max_needed)
    print(f"  Fetched {len(raw_docs)} docs")

    all_docs = {
        "enrichment":          raw_docs[:1],
        "hot_topics":          raw_docs[:15],
        "relationship_network": raw_docs,
    }

    client = OpenAI(base_url=args.llm, api_key="EMPTY", timeout=LLM_TIMEOUT)

    model_results: dict[str, dict] = {}

    for model in models:
        ctx = get_model_ctx(args.llm, model)
        print(f"\n{'═'*60}")
        print(f"  Testing: {model}  (ctx={ctx})")
        print(f"{'═'*60}")
        try:
            data = benchmark_model(client, model, all_docs, reps=args.reps)
            data["_ctx"] = ctx
            model_results[model] = data
        except Exception as e:
            print(f"  [SKIP] {model} failed: {e}")

    report = format_report(model_results, run_ts, args.index)
    out_path.write_text(report)

    # Print summary table
    print("\n" + "=" * 60)
    print("REPORT SUMMARY")
    print("=" * 60)
    print(report)
    print(f"\nFull report → {out_path}")


if __name__ == "__main__":
    main()
