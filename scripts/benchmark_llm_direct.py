#!/usr/bin/env python3
"""
benchmark_llm_direct.py — Raw LLM latency benchmark (no app stack).

Fetches real documents from Elasticsearch, builds minimal insight prompts,
and calls Ollama directly via the OpenAI-compatible API. Simulates sequential
batches of 1, 3, 5, and 10 LLM calls, measuring per-call and batch latency.

Usage:
    python scripts/benchmark_llm_direct.py [--index qsint_docs_europe] [--model qwen3.5:9b]

Results are written to benchmarks/results/bench_llm_direct_<timestamp>.md
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from openai import OpenAI

# ── Configuration ──────────────────────────────────────────────────────────────

DEFAULT_LLM_BASE_URL   = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
DEFAULT_ES_HOST        = os.getenv("ES_HOST", "http://localhost:9200")
DEFAULT_INDEX          = "qsint_docs_europe"
BATCH_SIZES            = [1, 3, 5, 10]
SAMPLE_DOCS_COUNT      = 50   # How many docs to fetch for general tasks
RELNET_DOCS_COUNT      = 70   # Docs for relationship_network (the heaviest task)
LLM_TIMEOUT            = 360  # seconds

RESULTS_DIR = Path(__file__).parent.parent / "benchmarks" / "results"

# ── Prompt templates (mirrors insights_engine task prompts) ───────────────────

INSIGHTS_HOT_TOPICS_SCHEMA = """{
  "hot_topics": [
    {"topic": "string", "sentiment_score": 0.0, "sentiment_label": "positive|negative|neutral|hostile", "brief_context": "string"}
  ]
}"""

SYSTEM_PROMPT = (
    "You are a specialized intelligence extraction engine. "
    "Output ONLY valid JSON that exactly matches the requested schema. "
    "Do not output any text before or after the JSON object."
)

INSIGHTS_GRAPH_PROMPT = """Detect communities of related entities across ALL provided documents and build a knowledge graph centred on those communities.

OBJECTIVE: Extract Named Entities (NER) then discover clusters (communities) of those entities that share significant relationships.

Allowed entity categories: PERSON, ORG, GPE (country/city), LOC, DATE, EVENT, PRODUCT, NORP, LAW, FAC.

FORMAT RULES:
1. Output ONLY valid JSON, no markdown, no comments, no preamble.
2. Use the entity name as the node "id".
3. Node "type" must be one of: person, org, gpe, loc, date, event, product, norp, law, fac.
4. Aim for 15-25 nodes and 20-40 edges (only if corpus supports it). Every node must have at least 2 edges.
5. Assign each node a "community" integer (0-based). Aim for 4-10 distinct communities.
6. The JSON must have EXACTLY this structure:
{
  "nodes": [{"id": "EntityName", "label": "EntityName", "type": "org", "community": 0}],
  "edges": [{"source": "Entity1", "target": "Entity2", "relationship": "string", "weight": 0.8}]
}
7. source and target must match node id values exactly.
8. Do NOT include any other top-level keys."""

TASK_VARIANTS = [
    {
        "name": "hot_topics_sentiment",
        "rules": "List discrete topics mentioned across the corpus. sentiment_score: -1.0 to 1.0. Up to 10 topics.",
        "schema": INSIGHTS_HOT_TOPICS_SCHEMA,
    },
    {
        "name": "trending_signals",
        "rules": "Identify rising or falling signals. Up to 5 signals.",
        "schema": '{"trending_signals": [{"label": "string", "direction": "rising|falling|stable", "change_summary": "string"}]}',
    },
    {
        "name": "active_narratives",
        "rules": "Discover high-level storylines. Up to 3 narratives.",
        "schema": '{"active_narratives": [{"title": "string", "description": "string", "sentiment": "string"}]}',
    },
]

RELATIONSHIP_NETWORK_TASK = {
    "name": "relationship_network",
    "rules": INSIGHTS_GRAPH_PROMPT,
    "schema": '{"nodes": [{"id": "string", "label": "string", "type": "string", "community": 0}], "edges": [{"source": "string", "target": "string", "relationship": "string", "weight": 0.8}]}',
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def discover_model(base_url: str) -> str:
    """Discover the active model via the standard OpenAI GET /v1/models endpoint.

    Works with SGLang, vLLM, and Ollama.
    """
    resp = requests.get(f"{base_url}/models", timeout=10)
    resp.raise_for_status()
    models = resp.json().get("data", [])
    if not models:
        raise RuntimeError("No models found on inference server")
    # Prefer instruct/chat variants
    instruct = [m["id"] for m in models if "instruct" in m.get("id", "").lower()]
    return instruct[0] if instruct else models[0]["id"]


def fetch_es_docs(es_host: str, index: str, count: int) -> list[dict]:
    """Fetch a random sample of documents from Elasticsearch."""
    url = f"{es_host}/{index}/_search"
    body = {
        "size": count,
        "query": {"function_score": {"query": {"match_all": {}}, "random_score": {}}},
        "_source": ["title", "text", "topic", "sentiment"],
    }
    resp = requests.post(url, json=body, timeout=30)
    resp.raise_for_status()
    hits = resp.json().get("hits", {}).get("hits", [])
    docs = []
    for h in hits:
        src = h.get("_source", {})
        docs.append({
            "title":     (src.get("title") or "")[:120],
            "topic":     src.get("topic", ""),
            "sentiment": src.get("sentiment", ""),
            "text":      (src.get("text") or "")[:800],
        })
    return docs


def build_prompt(docs: list[dict], task: dict) -> str:
    """Build a compact insight prompt from a list of docs."""
    lines = []
    for doc in docs:
        parts = []
        if doc.get("title"):     parts.append(f"title={doc['title']!r}")
        if doc.get("topic"):     parts.append(f"topic={doc['topic']!r}")
        if doc.get("sentiment"): parts.append(f"sentiment={doc['sentiment']!r}")
        if doc.get("text"):      parts.append(f"text={doc['text']!r}")
        lines.append(f"[{', '.join(parts)}]")

    doc_block = "\n".join(lines)
    n = len(lines)
    return (
        f"=== INTELLIGENCE CORPUS ({n} documents) ===\n"
        f"{doc_block}\n"
        f"=== END CORPUS ===\n\n"
        f"Analyse the {n} documents above.\n\n"
        f"{task['rules']}\n\n"
        f"Output ONLY the following JSON structure:\n{task['schema']}"
    )


def call_llm(client: OpenAI, model: str, prompt: str) -> tuple[float, int, bool]:
    """Single LLM call. Returns (elapsed_s, response_tokens, success)."""
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            stream=False,
            timeout=LLM_TIMEOUT,
        )
        elapsed = time.perf_counter() - t0
        tokens  = resp.usage.completion_tokens if resp.usage else 0
        return elapsed, tokens, True
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"    [ERR] LLM call failed after {elapsed:.1f}s: {e}", file=sys.stderr)
        return elapsed, 0, False


def run_batch(client: OpenAI, model: str, docs: list[dict], n: int, label: str) -> list[dict]:
    """Run n sequential LLM calls with varied task types. Returns per-call results."""
    results = []
    print(f"\n  Running {n} sequential calls ({label})...")
    for i in range(n):
        task   = TASK_VARIANTS[i % len(TASK_VARIANTS)]
        # Use a rotating slice of docs so each call has context
        sample = docs[:20] if len(docs) >= 20 else docs
        prompt = build_prompt(sample, task)
        print(f"    [{i+1}/{n}] task={task['name']} prompt_chars={len(prompt):,} ...", end="", flush=True)
        elapsed, tokens, ok = call_llm(client, model, prompt)
        status = "OK" if ok else "ERR"
        print(f" {elapsed:.2f}s | {tokens} tok | {status}")
        results.append({
            "call_n":   i + 1,
            "task":     task["name"],
            "elapsed":  round(elapsed, 3),
            "tokens":   tokens,
            "ok":       ok,
            "prompt_chars": len(prompt),
        })
    return results


def stats(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "min":  round(min(s), 3),
        "max":  round(max(s), 3),
        "avg":  round(sum(s) / n, 3),
        "p50":  round(s[int(n * 0.50)], 3),
        "p95":  round(s[min(int(n * 0.95), n - 1)], 3),
    }


def _batch_table_rows(results: list[dict]) -> list[str]:
    rows = [
        "| # | Task | Elapsed (s) | Tokens | Prompt chars | Status |",
        "|---|------|-------------|--------|--------------|--------|",
    ]
    for r in results:
        status = "✅" if r["ok"] else "❌"
        rows.append(
            f"| {r['call_n']} | {r['task']} | {r['elapsed']:.2f} | {r['tokens']} | {r.get('prompt_chars',0):,} | {status} |"
        )
    return rows


def _summary_table_rows(batches: dict[int, list[dict]]) -> list[str]:
    rows = [
        "| Batch | Total (s) | Avg/call (s) | Min (s) | Max (s) | p95 (s) | Errors |",
        "|-------|-----------|--------------|---------|---------|---------|--------|",
    ]
    for n, results in sorted(batches.items()):
        times     = [r["elapsed"] for r in results]
        err_count = sum(1 for r in results if not r["ok"])
        st        = stats(times)
        rows.append(
            f"| {n} | {sum(times):.2f} | {st.get('avg','?')} | "
            f"{st.get('min','?')} | {st.get('max','?')} | "
            f"{st.get('p95','?')} | {err_count} |"
        )
    return rows


def format_report(
    model: str, index: str, doc_count: int,
    all_results: dict[int, list[dict]],
    run_ts: str,
    relnet_results: dict[int, list[dict]] | None = None,
    relnet_doc_count: int = 0,
) -> str:
    lines = [
        "# LLM Direct Benchmark Report",
        "",
        f"**Date:** {run_ts}",
        f"**Mode:** Direct Ollama API (no app stack)",
        f"**Model:** `{model}`",
        f"**ES Index:** `{index}`",
        f"**General tasks docs:** {doc_count}",
        f"**Relationship network docs:** {relnet_doc_count}",
        f"**Call order:** sequential (LLM_PARALLEL=1 equivalent)",
        f"**Task variants rotated:** {', '.join(t['name'] for t in TASK_VARIANTS)}",
        "",
        "---",
        "",
        "## General Insight Tasks (hot_topics / trending / narratives)",
        "",
    ]

    for n, results in sorted(all_results.items()):
        ok_results = [r for r in results if r["ok"]]
        err_count  = len(results) - len(ok_results)
        times      = [r["elapsed"] for r in results]
        total      = round(sum(times), 3)
        st         = stats(times)

        lines += [f"### {n} sequential call{'s' if n > 1 else ''}",""] + _batch_table_rows(results) + [
            "",
            f"**Total:** {total:.2f}s | **Avg/call:** {st.get('avg','?')}s | "
            f"**Min:** {st.get('min','?')}s | **Max:** {st.get('max','?')}s | "
            f"**p95:** {st.get('p95','?')}s | **Errors:** {err_count}",
            "",
        ]

    lines += ["---", "", "### General Tasks Summary", ""] + _summary_table_rows(all_results)

    # ── Relationship Network section ───────────────────────────────────────────
    if relnet_results:
        lines += [
            "",
            "---",
            "",
            f"## Relationship Network Task ({relnet_doc_count} docs — heaviest task)",
            "",
            "> This task sends the largest prompt: full NER + graph construction instructions",
            "> plus all document text. It tests worst-case LLM latency.",
            "",
        ]
        for n, results in sorted(relnet_results.items()):
            ok_results = [r for r in results if r["ok"]]
            err_count  = len(results) - len(ok_results)
            times      = [r["elapsed"] for r in results]
            total      = round(sum(times), 3)
            st         = stats(times)

            lines += [f"### {n} sequential call{'s' if n > 1 else ''}",""] + _batch_table_rows(results) + [
                "",
                f"**Total:** {total:.2f}s | **Avg/call:** {st.get('avg','?')}s | "
                f"**Min:** {st.get('min','?')}s | **Max:** {st.get('max','?')}s | "
                f"**p95:** {st.get('p95','?')}s | **Errors:** {err_count}",
                "",
            ]

        lines += ["", "### Relationship Network Summary", ""] + _summary_table_rows(relnet_results)

    lines += [
        "",
        "---",
        "",
        "## Observations",
        "",
        "*(Auto-generated — review and annotate)*",
        "",
        "- First call may be slower due to model warmup / KV-cache cold start.",
        "- Subsequent calls may be faster if GPU stays hot (no context eviction).",
        "- Large prompts (many docs, large graph instructions) increase TTFT significantly.",
        "- `relationship_network` sends the longest prompt — compare its latency to",
        "  simpler tasks to understand the per-token cost.",
        "- GPU utilisation observed during run: ~28% (RTX 3080, 115W). Low utilisation",
        "  may indicate CPU-side tokenization or HTTP overhead between calls.",
    ]

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Direct LLM latency benchmark")
    parser.add_argument("--index",  default=DEFAULT_INDEX,        help="ES index to sample from")
    parser.add_argument("--model",  default=None,                  help="Ollama model name (auto-discover if omitted)")
    parser.add_argument("--es",     default=DEFAULT_ES_HOST,       help="Elasticsearch host")
    parser.add_argument("--llm",    default=DEFAULT_LLM_BASE_URL,  help="Ollama base URL")
    parser.add_argument("--docs",   default=SAMPLE_DOCS_COUNT, type=int, help="ES docs to fetch for prompts")
    args = parser.parse_args()

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"bench_llm_direct_{ts}.md"

    print("=" * 60)
    print("LLM Direct Benchmark")
    print("=" * 60)

    # Discover model
    model = args.model or discover_model(args.llm)
    print(f"Model      : {model}")
    print(f"LLM URL    : {args.llm}")
    print(f"ES Index   : {args.index}")

    # Fetch real docs from ES
    print(f"\nFetching {args.docs} docs from ES ({args.index})...")
    t_es = time.perf_counter()
    docs = fetch_es_docs(args.es, args.index, args.docs)
    print(f"  Got {len(docs)} docs in {time.perf_counter() - t_es:.2f}s")

    if not docs:
        print("ERROR: No docs fetched from ES — check --index and --es", file=sys.stderr)
        sys.exit(1)

    # Build OpenAI client pointing at Ollama
    client = OpenAI(base_url=args.llm, api_key="EMPTY", timeout=LLM_TIMEOUT)

    # Warmup call (not included in results)
    print("\nWarmup call (not recorded)...")
    task0 = TASK_VARIANTS[0]
    prompt0 = build_prompt(docs[:5], task0)
    elapsed0, _, ok0 = call_llm(client, model, prompt0)
    print(f"  Warmup: {elapsed0:.2f}s {'OK' if ok0 else 'ERR'}")

    # ── General insight task batches ───────────────────────────────────────────
    print("\n" + "═"*60)
    print("GENERAL INSIGHT TASKS (hot_topics / trending / narratives)")
    print("═"*60)
    all_results: dict[int, list[dict]] = {}
    for n in BATCH_SIZES:
        print(f"\n{'─'*50}")
        print(f"Batch: {n} sequential call{'s' if n > 1 else ''}")
        results = run_batch(client, model, docs, n, label=f"n={n}")
        all_results[n] = results
        if n != BATCH_SIZES[-1]:
            print("  (pausing 3s between batches...)")
            time.sleep(3)

    # ── Relationship network batches (heavy task) ───────────────────────────────
    print("\n" + "═"*60)
    print(f"RELATIONSHIP NETWORK (heaviest task — {RELNET_DOCS_COUNT} docs)")
    print("═"*60)

    print(f"\nFetching {RELNET_DOCS_COUNT} docs for relationship_network...")
    docs_rn = fetch_es_docs(args.es, args.index, RELNET_DOCS_COUNT)
    print(f"  Got {len(docs_rn)} docs")

    relnet_results: dict[int, list[dict]] = {}
    for n in BATCH_SIZES:
        print(f"\n{'─'*50}")
        print(f"Batch: {n} sequential call{'s' if n > 1 else ''} [relationship_network]")
        results = []
        print(f"\n  Running {n} sequential calls (n={n})...")
        for i in range(n):
            sample = docs_rn
            prompt = build_prompt(sample, RELATIONSHIP_NETWORK_TASK)
            print(f"    [{i+1}/{n}] task=relationship_network prompt_chars={len(prompt):,} ...", end="", flush=True)
            elapsed, tokens, ok = call_llm(client, model, prompt)
            status = "OK" if ok else "ERR"
            print(f" {elapsed:.2f}s | {tokens} tok | {status}")
            results.append({
                "call_n":   i + 1,
                "task":     "relationship_network",
                "elapsed":  round(elapsed, 3),
                "tokens":   tokens,
                "ok":       ok,
                "prompt_chars": len(prompt),
            })
        relnet_results[n] = results
        if n != BATCH_SIZES[-1]:
            print("  (pausing 3s between batches...)")
            time.sleep(3)

    # Write report
    report = format_report(model, args.index, len(docs), all_results, run_ts, relnet_results=relnet_results, relnet_doc_count=len(docs_rn))
    out_path.write_text(report)
    print(f"\n{'='*60}")
    print(f"Report written → {out_path}")
    print("=" * 60)

    # Print summary to stdout
    print("\nGeneral Tasks Summary:")
    print(f"{'Batch':>6}  {'Total':>8}  {'Avg/call':>10}  {'Max':>8}")
    for n, results in sorted(all_results.items()):
        times = [r["elapsed"] for r in results]
        total = sum(times)
        avg   = total / len(times) if times else 0
        mx    = max(times) if times else 0
        print(f"{n:>6}  {total:>7.2f}s  {avg:>9.2f}s  {mx:>7.2f}s")

    print("\nRelationship Network Summary:")
    print(f"{'Batch':>6}  {'Total':>8}  {'Avg/call':>10}  {'Max':>8}")
    for n, results in sorted(relnet_results.items()):
        times = [r["elapsed"] for r in results]
        total = sum(times)
        avg   = total / len(times) if times else 0
        mx    = max(times) if times else 0
        print(f"{n:>6}  {total:>7.2f}s  {avg:>9.2f}s  {mx:>7.2f}s")


if __name__ == "__main__":
    main()
