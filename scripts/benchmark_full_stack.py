#!/usr/bin/env python3
"""
benchmark_full_stack.py — Full stack LLM latency benchmark.

Exercises the real app pipeline:
  ES (retriever.get_sample) → PromptBuilder.build_insights_messages
  → LLMClient.complete_json (via get_llm())

Simulates LLM_PARALLEL=1 (sequential execution, same as production config).
Tests batches of 1, 3, 5, 10 sequential insight-type calls.

Also benchmarks enrichment (single-doc) calls for comparison.

Usage:
    cd /home/bogdan/workspace/dev/rag-poc
    python scripts/benchmark_full_stack.py [--index qsint_docs_europe]

Results → benchmarks/results/bench_full_stack_<timestamp>.md
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Bootstrap project path ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load env before importing src modules
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── Now import project modules ─────────────────────────────────────────────────
from src.config import Config  # noqa: E402
from src.rag.llm_client import get_llm  # noqa: E402
from src.rag.prompt_builder import PromptBuilder  # noqa: E402
from src.rag.retriever import get_retriever  # noqa: E402

BATCH_SIZES        = [1, 3, 5, 10]
RESULTS_DIR        = PROJECT_ROOT / "benchmarks" / "results"
RELNET_DOCS_COUNT  = 70   # Docs to feed into relationship_network (heaviest task)

# General insight tasks (rotated across calls in each batch)
AI_TASK_TYPES = [
    "hot_topics_sentiment",
    "trending_signals",
    "active_narratives",
]

# Dedicated heavy task benchmarked separately with more docs
RELNET_TASK = "relationship_network"

ENRICH_TASK_TYPES = [
    "sentiment",
    "classification",
    "summary",
    "entities",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

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


def run_insight_call(
    llm, builder: PromptBuilder, sample: list[dict], task_type: str
) -> tuple[float, int, bool, str]:
    """Single insight LLM call. Returns (elapsed_s, resp_len, ok, error)."""
    t0 = time.perf_counter()
    try:
        messages, system = builder.build_insights_messages(sample, task_type=task_type)
        prompt_chars = sum(len(m["content"]) for m in messages) + len(system)
        raw = llm.complete_json(
            messages, system,
            num_ctx=Config.LLM_INSIGHTS_CTX,
            max_tokens=Config.LLM_INSIGHTS_MAX_TOKENS,
        )
        elapsed = time.perf_counter() - t0
        return elapsed, len(raw), True, ""
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return elapsed, 0, False, str(e)


def run_enrich_call(
    llm, builder: PromptBuilder, doc_text: str, field: str
) -> tuple[float, int, bool, str]:
    """Single enrichment LLM call. Returns (elapsed_s, resp_len, ok, error)."""
    t0 = time.perf_counter()
    try:
        messages, system = builder.build_field_enrichment_messages(doc_text[:3000], field)
        raw = llm.complete_json(messages, system)
        elapsed = time.perf_counter() - t0
        return elapsed, len(raw), True, ""
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return elapsed, 0, False, str(e)


def run_insight_batch(
    llm, builder: PromptBuilder, sample: list[dict], n: int
) -> list[dict]:
    """Run n sequential insight calls, rotating task types."""
    results = []
    print(f"\n  Insights — {n} sequential call{'s' if n > 1 else ''}...")
    for i in range(n):
        task = AI_TASK_TYPES[i % len(AI_TASK_TYPES)]
        print(f"    [{i+1}/{n}] task={task} ...", end="", flush=True)
        elapsed, resp_len, ok, err = run_insight_call(llm, builder, sample, task)
        status = "OK" if ok else f"ERR: {err[:60]}"
        print(f" {elapsed:.2f}s | {resp_len} chars | {status}")
        results.append({
            "call_n":    i + 1,
            "kind":      "insight",
            "task":      task,
            "elapsed":   round(elapsed, 3),
            "resp_len":  resp_len,
            "ok":        ok,
            "error":     err,
        })
    return results


def run_enrich_batch(
    llm, builder: PromptBuilder, doc_text: str, n: int
) -> list[dict]:
    """Run n sequential enrichment calls."""
    results = []
    print(f"\n  Enrichment — {n} sequential call{'s' if n > 1 else ''}...")
    for i in range(n):
        field = ENRICH_TASK_TYPES[i % len(ENRICH_TASK_TYPES)]
        print(f"    [{i+1}/{n}] field={field} ...", end="", flush=True)
        elapsed, resp_len, ok, err = run_enrich_call(llm, builder, doc_text, field)
        status = "OK" if ok else f"ERR: {err[:60]}"
        print(f" {elapsed:.2f}s | {resp_len} chars | {status}")
        results.append({
            "call_n":   i + 1,
            "kind":     "enrich",
            "task":     field,
            "elapsed":  round(elapsed, 3),
            "resp_len": resp_len,
            "ok":       ok,
            "error":    err,
        })
    return results


def format_batch_table(results: list[dict]) -> list[str]:
    lines = [
        "| # | Task | Elapsed (s) | Resp chars | Status |",
        "|---|------|-------------|------------|--------|",
    ]
    for r in results:
        status = "✅" if r["ok"] else f"❌ {r.get('error','')[:40]}"
        lines.append(
            f"| {r['call_n']} | {r['task']} | {r['elapsed']:.2f} | {r['resp_len']} | {status} |"
        )
    return lines


def run_relnet_batch(
    llm, builder: PromptBuilder, sample: list[dict], n: int
) -> list[dict]:
    """Run n sequential relationship_network calls with all docs in sample."""
    results = []
    print(f"\n  Relationship Network — {n} sequential call{'s' if n > 1 else ''}...")
    for i in range(n):
        print(f"    [{i+1}/{n}] task=relationship_network docs={len(sample)} ...", end="", flush=True)
        elapsed, resp_len, ok, err = run_insight_call(llm, builder, sample, RELNET_TASK)
        status = "OK" if ok else f"ERR: {err[:60]}"
        print(f" {elapsed:.2f}s | {resp_len} chars | {status}")
        results.append({
            "call_n":   i + 1,
            "kind":     "insight",
            "task":     RELNET_TASK,
            "elapsed":  round(elapsed, 3),
            "resp_len": resp_len,
            "ok":       ok,
            "error":    err,
        })
    return results


def format_report(
    model: str, index: str, doc_count: int,
    insight_batches: dict[int, list[dict]],
    enrich_batches: dict[int, list[dict]],
    run_ts: str,
    relnet_batches: dict[int, list[dict]] | None = None,
    relnet_doc_count: int = 0,
) -> str:
    def _batch_section(section_results: dict[int, list[dict]], label: str) -> list[str]:
        out = []
        for n, results in sorted(section_results.items()):
            ok_results = [r for r in results if r["ok"]]
            err_count  = len(results) - len(ok_results)
            times      = [r["elapsed"] for r in results]
            total      = round(sum(times), 3)
            st         = stats(times)
            out += [
                f"### {n} sequential {label} call{'s' if n > 1 else ''}",
                "",
            ] + format_batch_table(results) + [
                "",
                f"**Total:** {total:.2f}s | **Avg/call:** {st.get('avg','?')}s | "
                f"**Min:** {st.get('min','?')}s | **Max:** {st.get('max','?')}s | "
                f"**p95:** {st.get('p95','?')}s | **Errors:** {err_count}",
                "",
            ]
        return out

    def _summary_table(section_results: dict[int, list[dict]]) -> list[str]:
        rows = [
            "| Batch | Total (s) | Avg/call (s) | Min (s) | Max (s) | p95 (s) | Errors |",
            "|-------|-----------|--------------|---------|---------|---------|--------|",
        ]
        for n, results in sorted(section_results.items()):
            times     = [r["elapsed"] for r in results]
            err_count = sum(1 for r in results if not r["ok"])
            st        = stats(times)
            rows.append(
                f"| {n} | {sum(times):.2f} | {st.get('avg','?')} | "
                f"{st.get('min','?')} | {st.get('max','?')} | "
                f"{st.get('p95','?')} | {err_count} |"
            )
        return rows

    lines = [
        "# Full Stack LLM Benchmark Report",
        "",
        f"**Date:** {run_ts}",
        f"**Mode:** Full stack (retriever → PromptBuilder → LLMClient)",
        f"**Model:** `{model}`",
        f"**ES Index:** `{index}`",
        f"**General insight docs:** {doc_count}",
        f"**Relationship network docs:** {relnet_doc_count}",
        f"**LLM_PARALLEL:** 1 (sequential)",
        f"**LLM_TIMEOUT:** {Config.LLM_TIMEOUT}s",
        f"**LLM_INSIGHTS_CTX:** {Config.LLM_INSIGHTS_CTX} tokens",
        f"**LLM_INSIGHTS_MAX_TOKENS:** {Config.LLM_INSIGHTS_MAX_TOKENS}",
        f"**LLM_TEMPERATURE:** {Config.LLM_TEMPERATURE}",
        "",
        "---",
        "",
        "## Insight Tasks (corpus-level analysis)",
        "",
        f"Task types rotated: {', '.join(AI_TASK_TYPES)}",
        "",
    ] + _batch_section(insight_batches, "insight") + [
        "---",
        "",
        "### Insight Tasks Summary",
        "",
    ] + _summary_table(insight_batches)

    # ── Relationship Network section ───────────────────────────────────────────
    if relnet_batches:
        lines += [
            "",
            "---",
            "",
            f"## Relationship Network Task ({relnet_doc_count} docs — heaviest task)",
            "",
            "> Sends the largest prompt: full NER + community graph instructions + all doc text.",
            "> This is the worst-case scenario for LLM latency in this pipeline.",
            "",
        ] + _batch_section(relnet_batches, "relationship_network") + [
            "### Relationship Network Summary",
            "",
        ] + _summary_table(relnet_batches)

    lines += [
        "",
        "---",
        "",
        "## Enrichment Tasks (per-document)",
        "",
        f"Field types rotated: {', '.join(ENRICH_TASK_TYPES)}",
        "",
    ] + _batch_section(enrich_batches, "enrichment") + [
        "### Enrichment Tasks Summary",
        "",
    ] + _summary_table(enrich_batches) + [
        "",
        "---",
        "",
        "## Observations",
        "",
        "*(Auto-generated — review and annotate)*",
        "",
        "- **Insight tasks** pack many documents into the context → larger prompts → longer TTFT.",
        "- **Relationship network** is the worst case: NER + graph with 70+ docs.",
        "  Compare its avg/call to simpler tasks to understand prompt-size cost.",
        "- **Enrichment tasks** process one doc at a time → much shorter prompts → faster.",
        "- Retriever overhead (ES sample fetch) is NOT included in per-call timing.",
        "- Compare Avg/call here vs. benchmark_llm_direct.py to see app-stack overhead.",
        "- GPU observation during run: RTX 3080 at ~28% (115W / 320W cap). Low GPU util",
        "  may indicate bottleneck is at tokenization, HTTP, or model is too small to",
        "  saturate the GPU. Larger models (7B+) may use more GPU and generate faster.",
    ]

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Full stack LLM latency benchmark")
    parser.add_argument("--index", default="qsint_docs_europe", help="ES index to sample docs from")
    parser.add_argument("--docs",  default=100, type=int,        help="Docs to sample from ES")
    args = parser.parse_args()

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"bench_full_stack_{ts}.md"

    print("=" * 60)
    print("Full Stack LLM Benchmark")
    print("=" * 60)

    # ── Init stack ─────────────────────────────────────────────────────────────
    print("\nInitialising LLM client...")
    t0 = time.perf_counter()
    llm = get_llm()
    print(f"  Model: {llm.model_name}  ({time.perf_counter()-t0:.2f}s)")

    builder = PromptBuilder()

    print(f"\nFetching {args.docs} docs from ES ({args.index})...")
    t0 = time.perf_counter()
    retriever = get_retriever()
    sample = retriever.get_sample(args.docs, index_name=args.index)
    print(f"  Got {len(sample)} docs in {time.perf_counter()-t0:.2f}s")

    if not sample:
        print("ERROR: No docs returned from ES — check --index", file=sys.stderr)
        sys.exit(1)

    # Pick a single doc for enrichment tests (use the longest one for realism)
    enrich_doc = max(sample, key=lambda d: len(d.get("text") or ""))
    enrich_text = (enrich_doc.get("text") or "")[:3000]
    print(f"  Enrichment doc: id={enrich_doc.get('id','?')} text_len={len(enrich_text)}")

    # ── Warmup ─────────────────────────────────────────────────────────────────
    print("\nWarmup call (not recorded)...")
    t0 = time.perf_counter()
    try:
        msgs, sys_ = builder.build_insights_messages(sample[:5], "hot_topics_sentiment")
        llm.complete_json(msgs, sys_)
        print(f"  Warmup OK in {time.perf_counter()-t0:.2f}s")
    except Exception as e:
        print(f"  Warmup ERR: {e}")

    # ── General insight batches ────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("INSIGHT TASKS (hot_topics / trending / narratives)")
    print("═" * 60)

    insight_batches: dict[int, list[dict]] = {}
    for n in BATCH_SIZES:
        print(f"\n{'─'*50}")
        results = run_insight_batch(llm, builder, sample, n)
        insight_batches[n] = results
        if n != BATCH_SIZES[-1]:
            print("  (pausing 2s...)")
            time.sleep(2)

    # ── Relationship Network batches (heavy task) ──────────────────────────────
    print("\n" + "═" * 60)
    print(f"RELATIONSHIP NETWORK ({RELNET_DOCS_COUNT} docs — heaviest task)")
    print("═" * 60)

    print(f"\nFetching {RELNET_DOCS_COUNT} docs for relationship_network from ES...")
    t0 = time.perf_counter()
    relnet_sample = retriever.get_sample(RELNET_DOCS_COUNT, index_name=args.index)
    print(f"  Got {len(relnet_sample)} docs in {time.perf_counter()-t0:.2f}s")

    relnet_batches: dict[int, list[dict]] = {}
    for n in BATCH_SIZES:
        print(f"\n{'─'*50}")
        results = run_relnet_batch(llm, builder, relnet_sample, n)
        relnet_batches[n] = results
        if n != BATCH_SIZES[-1]:
            print("  (pausing 2s...)")
            time.sleep(2)

    # ── Enrichment batches ─────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("ENRICHMENT TASKS (per-document)")
    print("═" * 60)

    enrich_batches: dict[int, list[dict]] = {}
    for n in BATCH_SIZES:
        print(f"\n{'─'*50}")
        results = run_enrich_batch(llm, builder, enrich_text, n)
        enrich_batches[n] = results
        if n != BATCH_SIZES[-1]:
            print("  (pausing 2s...)")
            time.sleep(2)

    # ── Write report ───────────────────────────────────────────────────────────
    report = format_report(
        model=llm.model_name,
        index=args.index,
        doc_count=len(sample),
        insight_batches=insight_batches,
        enrich_batches=enrich_batches,
        run_ts=run_ts,
        relnet_batches=relnet_batches,
        relnet_doc_count=len(relnet_sample),
    )
    out_path.write_text(report)

    print(f"\n{'='*60}")
    print(f"Report written → {out_path}")
    print("=" * 60)

    def _print_summary(label: str, batches: dict[int, list[dict]]):
        print(f"\n{label}:")
        print(f"  {'Batch':>6}  {'Total':>8}  {'Avg/call':>10}  {'Max':>8}")
        for n, results in sorted(batches.items()):
            times = [r["elapsed"] for r in results]
            total = sum(times)
            avg   = total / len(times) if times else 0
            mx    = max(times) if times else 0
            print(f"  {n:>6}  {total:>7.2f}s  {avg:>9.2f}s  {mx:>7.2f}s")

    _print_summary("Insight Tasks", insight_batches)
    _print_summary(f"Relationship Network ({len(relnet_sample)} docs)", relnet_batches)
    _print_summary("Enrichment Tasks", enrich_batches)


if __name__ == "__main__":
    main()
