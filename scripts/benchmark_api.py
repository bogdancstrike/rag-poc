#!/usr/bin/env python3
"""
benchmark_api.py — Full-stack latency benchmark via real API endpoints.

Simulates actual app usage:
  - Enrichment: POST /rag/v1/documents/enrich, polls until task complete
  - Insight task: POST /rag/v1/insights/task/refresh, polls until complete
  - All tasks appear in Task Monitor just like real user activity

Usage:
    python scripts/benchmark_api.py [--api http://localhost:5100/rag]
                                    [--datasource qsint_docs_financial_crime]
                                    [--investigation inv_elections_romania_investigation_c0424d3a]

Results → benchmarks/results/bench_api_<timestamp>.md  (also printed here)

Target SLAs (from user requirements):
  Enrichment task   : ≤ 10 s
  Relationship graph : ≤ 30 s
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_API           = os.getenv("BENCH_API", "http://localhost:5100/rag")
DEFAULT_DATASOURCE    = "qsint_docs_financial_crime"
DEFAULT_INVESTIGATION = None   # auto-discover from API
POLL_INTERVAL         = 0.5   # seconds between status polls
POLL_TIMEOUT          = 180   # give up after this many seconds
RESULTS_DIR           = Path(__file__).parent.parent / "benchmarks" / "results"

ENRICHMENT_DOC = {
    "datasource": DEFAULT_DATASOURCE,
    "doc_id":     "e252bb94-ad0e-4a0a-a7db-c784662ef6f1",
    "text": (
        "Case: FINCRIME-006996\nClassification: RESTRICTED\nAnalyst: Phyllis Evans\n\n"
        "EXECUTIVE SUMMARY\nA crypto bridge exploit has been identified, orchestrated by Chinese crypto "
        "laundering operation. Funds totalling approximately €397,182,832 implicated across 1958 accounts. "
        "Primary layering jurisdiction: Belize. Vehicle: Bitcoin (BTC).\n\n"
        "FINANCIAL FLOW ANALYSIS\nBoth project pay cell tend security create. Evening series then side.\n"
        "Meet on people space.\nInclude shoulder camera member beyond after three. Exist position detail on your.\n"
        "Model especially have business just take focus wish. What amount later.\n"
        "Kind company Mr entire although kid design always. Nature democratic degree.\n"
        "Vote as no large walk. Difficult member prevent trip tend some work.\n"
        "Catch party without. Green result society now us.\n"
        "Her truth coach blue. Thing every who thing toward time compare increase. Stop which total.\n"
        "The cryptocurrency exchange sector was used as the primary integration channel. "
        "Shell companies in Belize and Marshall Islands were identified as key nodes.\n\n"
        "BLOCKCHAIN FORENSICS\nWallet cluster: 1108243299527f4a3eef313dd078cc8d95\n"
        "Associated exchange: unregulated P2P exchange\nMixing service: YoMix\n\n"
        "ATTRIBUTION\nAttributed to Chinese crypto laundering operation with 72% confidence "
        "based on TTP overlap and financial intelligence.\n"
        "Politics everything difference both. While treatment involve since development individual look. "
        "Brother fill walk as tough. Something table sort adult join drop. Seek short possible green leader "
        "yet suffer news. Hope Congress wind voice.\n"
    ),
    "force": True,
}

INSIGHT_TASKS = [
    "hot_topics_sentiment",
    "trending_signals",
    "active_narratives",
    "relationship_network",
]

TARGET_SLA = {
    "enrichment":          10,
    "hot_topics_sentiment": 30,
    "trending_signals":     30,
    "active_narratives":    30,
    "relationship_network": 30,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def get(api: str, path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{api}{path}", params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def post(api: str, path: str, body: dict) -> tuple[int, dict]:
    r = requests.post(f"{api}{path}", json=body, timeout=30)
    return r.status_code, (r.json() if r.content else {})


def discover_doc(api: str, datasource: str) -> tuple[str, str]:
    """Return (doc_id, doc_text) for a real document in the datasource."""
    try:
        d = get(api, "/v1/documents", {"datasource": datasource, "limit": 1})
        docs = d.get("documents", [])
        if docs:
            return docs[0]["id"], (docs[0].get("text") or "")[:2000]
    except Exception:
        pass
    return ENRICHMENT_DOC["doc_id"], ENRICHMENT_DOC["text"]


def discover_investigation(api: str) -> dict | None:
    """Return a ready investigation, or None."""
    try:
        d = get(api, "/v1/investigations")
        for inv in d.get("investigations", []):
            if inv.get("status") == "ready":
                return inv
    except Exception:
        pass
    return None


def poll_enrichment(api: str, datasource: str, doc_id: str, timeout: float) -> tuple[str, float]:
    """Poll enrichment status until complete/error. Returns (status, elapsed_s)."""
    t0 = time.perf_counter()
    while (elapsed := time.perf_counter() - t0) < timeout:
        try:
            d = get(api, "/v1/documents/enrichments", {"datasource": datasource, "doc_id": doc_id})
            enrichments = d.get("enrichments", [])
            if enrichments:
                status = enrichments[0].get("status", "unknown")
                if status in ("complete", "error"):
                    return status, elapsed
        except Exception as e:
            pass
        time.sleep(POLL_INTERVAL)
    return "timeout", time.perf_counter() - t0


def poll_insight_task(api: str, datasource: str, task: str, timeout: float) -> tuple[str, float]:
    """Poll insight task status until complete/error. Returns (status, elapsed_s)."""
    t0 = time.perf_counter()
    while (elapsed := time.perf_counter() - t0) < timeout:
        try:
            d = get(api, "/v1/insights", {"datasource": datasource})
            tasks = d.get("tasks", {})
            t_data = tasks.get(task, {})
            status = t_data.get("status", "unknown")
            if status in ("complete", "error"):
                return status, elapsed
        except Exception as e:
            pass
        time.sleep(POLL_INTERVAL)
    return "timeout", time.perf_counter() - t0


def sla_badge(elapsed: float, target: float) -> str:
    if elapsed <= target:
        return f"✅ {elapsed:.2f}s (target ≤{target}s)"
    return f"❌ {elapsed:.2f}s (target ≤{target}s — over by {elapsed-target:.1f}s)"


def stats(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "min": round(min(s), 2), "max": round(max(s), 2),
        "avg": round(sum(s) / n, 2),
        "p50": round(s[n // 2], 2),
        "p95": round(s[min(int(n * 0.95), n - 1)], 2),
    }


# ── Benchmark sections ─────────────────────────────────────────────────────────

def bench_enrichment(api: str, datasource: str, doc_id: str, doc_text: str, reps: int) -> list[dict]:
    results = []
    print(f"\n  Enrichment ({datasource}/{doc_id[:8]}…)")
    for i in range(reps):
        print(f"    rep {i+1}/{reps}  POST /enrich ... ", end="", flush=True)
        body = {"datasource": datasource, "doc_id": doc_id, "text": doc_text, "force": True}
        t_post = time.perf_counter()
        code, resp = post(api, "/v1/documents/enrich", body)
        if code not in (200, 202):
            print(f"ERR HTTP {code}")
            results.append({"rep": i+1, "elapsed": 0, "status": f"http_{code}", "ok": False})
            continue
        status, elapsed = poll_enrichment(api, datasource, doc_id, POLL_TIMEOUT)
        print(f"{elapsed:.2f}s → {status}  {sla_badge(elapsed, TARGET_SLA['enrichment'])}")
        results.append({"rep": i+1, "elapsed": round(elapsed, 3), "status": status, "ok": status == "complete"})
    return results


def bench_insight_task(api: str, datasource: str, task: str, reps: int) -> list[dict]:
    results = []
    target = TARGET_SLA.get(task, 30)
    print(f"\n  Insight task: {task} ({datasource})")
    for i in range(reps):
        # First invalidate so it runs fresh
        try:
            post(api, "/v1/insights/refresh", {"datasource": datasource})
        except Exception:
            pass
        print(f"    rep {i+1}/{reps}  POST /insights/task/refresh ... ", end="", flush=True)
        body = {"datasource": datasource, "task": task}
        code, resp = post(api, "/v1/insights/task/refresh", body)
        if code not in (200, 202):
            print(f"ERR HTTP {code}")
            results.append({"rep": i+1, "elapsed": 0, "status": f"http_{code}", "ok": False})
            continue
        status, elapsed = poll_insight_task(api, datasource, task, POLL_TIMEOUT)
        print(f"{elapsed:.2f}s → {status}  {sla_badge(elapsed, target)}")
        results.append({"rep": i+1, "elapsed": round(elapsed, 3), "status": status, "ok": status == "complete"})
    return results


# ── Report ─────────────────────────────────────────────────────────────────────

def format_report(
    all_results: dict,
    api: str,
    enrichment_ds: str,
    investigation_idx: str,
    run_ts: str,
) -> str:
    lines = [
        "# API Full-Stack Benchmark Report",
        "",
        f"**Date:** {run_ts}",
        f"**Mode:** Real HTTP endpoints → Kafka → LLM → DB (full production path)",
        f"**API:** `{api}`",
        f"**Enrichment datasource:** `{enrichment_ds}`",
        f"**Insight datasource:** `{investigation_idx}`",
        f"**Measurement:** wall-clock from POST trigger to task `complete`/`error`",
        "",
        "---",
        "",
        "## Enrichment Tasks",
        "",
        f"> **SLA target: ≤ {TARGET_SLA['enrichment']}s** (per-task, full enrichment via API)",
        "",
    ]

    enrich_data = all_results.get("enrichment", [])
    if enrich_data:
        times = [r["elapsed"] for r in enrich_data if r["ok"]]
        st = stats(times)
        lines += [
            "| Rep | Elapsed (s) | Status | SLA |",
            "|-----|-------------|--------|-----|",
        ]
        for r in enrich_data:
            sla = "✅" if r["ok"] and r["elapsed"] <= TARGET_SLA["enrichment"] else ("❌" if r["ok"] else "⚠️")
            lines.append(f"| {r['rep']} | {r['elapsed']:.2f} | {r['status']} | {sla} |")
        lines += [
            "",
            f"**Avg:** {st.get('avg','?')}s | **p95:** {st.get('p95','?')}s | "
            f"**Min:** {st.get('min','?')}s | **Max:** {st.get('max','?')}s",
            "",
        ]

    lines += [
        "---",
        "",
        "## Insight Tasks",
        "",
    ]

    for task in INSIGHT_TASKS:
        target = TARGET_SLA.get(task, 30)
        task_data = all_results.get(f"insight_{task}", [])
        if not task_data:
            continue
        times = [r["elapsed"] for r in task_data if r["ok"]]
        st = stats(times)
        lines += [
            f"### {task} (SLA: ≤ {target}s)",
            "",
            "| Rep | Elapsed (s) | Status | SLA |",
            "|-----|-------------|--------|-----|",
        ]
        for r in task_data:
            sla = "✅" if r["ok"] and r["elapsed"] <= target else ("❌" if r["ok"] else "⚠️")
            lines.append(f"| {r['rep']} | {r['elapsed']:.2f} | {r['status']} | {sla} |")
        lines += [
            "",
            f"**Avg:** {st.get('avg','?')}s | **p95:** {st.get('p95','?')}s | "
            f"**Min:** {st.get('min','?')}s | **Max:** {st.get('max','?')}s",
            "",
        ]

    lines += [
        "---",
        "",
        "## SLA Summary",
        "",
        "| Task | Avg (s) | p95 (s) | SLA target | Met? |",
        "|------|---------|---------|------------|------|",
    ]

    # Enrichment row
    enrich_times = [r["elapsed"] for r in all_results.get("enrichment", []) if r.get("ok")]
    if enrich_times:
        st = stats(enrich_times)
        met = "✅" if st["p95"] <= TARGET_SLA["enrichment"] else "❌"
        lines.append(f"| Enrichment (full) | {st['avg']} | {st['p95']} | ≤{TARGET_SLA['enrichment']}s | {met} |")

    for task in INSIGHT_TASKS:
        task_data = all_results.get(f"insight_{task}", [])
        times = [r["elapsed"] for r in task_data if r.get("ok")]
        if not times:
            continue
        st = stats(times)
        target = TARGET_SLA.get(task, 30)
        met = "✅" if st["p95"] <= target else "❌"
        lines.append(f"| {task} | {st['avg']} | {st['p95']} | ≤{target}s | {met} |")

    lines += [
        "",
        "---",
        "",
        "## Observations",
        "",
        "- Times include: HTTP round-trip + Kafka produce/consume latency + ES sample fetch",
        "  + PromptBuilder packing + LLM inference + DB write.",
        "- First call of each session may be slower (cold GPU KV cache).",
        "- `relationship_network` is the most complex task (NER + graph construction).",
        "- Full enrichment generates all fields at once (summary, entities, graph, timeline,",
        "  locations, language) — inherently larger output than per-field reload.",
    ]
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="API endpoint full-stack benchmark")
    parser.add_argument("--api",           default=DEFAULT_API)
    parser.add_argument("--datasource",    default=DEFAULT_DATASOURCE)
    parser.add_argument("--investigation", default=DEFAULT_INVESTIGATION,
                        help="Investigation index name. Auto-discovered if omitted.")
    parser.add_argument("--reps",          default=2, type=int)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"bench_api_{ts}.md"

    print("=" * 60)
    print("Full-Stack API Benchmark")
    print("=" * 60)
    print(f"API:         {args.api}")
    print(f"Datasource:  {args.datasource}")

    # Check API health
    try:
        r = requests.get(f"{args.api}/health", timeout=5)
        if r.status_code != 200:
            print(f"ERROR: API not healthy (HTTP {r.status_code})")
            sys.exit(1)
        print("API health:  OK")
    except Exception as e:
        print(f"ERROR: Can't reach API — {e}")
        sys.exit(1)

    # Discover a real doc for enrichment
    doc_id, doc_text = discover_doc(args.api, args.datasource)
    if not doc_text:
        doc_id, doc_text = ENRICHMENT_DOC["doc_id"], ENRICHMENT_DOC["text"]
    print(f"Enrich doc:  {doc_id} ({len(doc_text)} chars)")

    # Discover investigation for insight tasks
    inv_idx = args.investigation
    if not inv_idx:
        inv = discover_investigation(args.api)
        if inv:
            inv_idx = inv.get("index_name")
            print(f"Investigation: {inv.get('name')} → {inv_idx}")
        else:
            # Fall back to a regular ES index for insight tasks
            inv_idx = args.datasource
            print(f"Investigation: none found, using {inv_idx}")

    all_results: dict = {}

    # ── Enrichment ─────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("ENRICHMENT TASKS")
    print("═" * 60)
    all_results["enrichment"] = bench_enrichment(
        args.api, args.datasource, doc_id, doc_text, reps=args.reps
    )

    # ── Insight tasks ───────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print(f"INSIGHT TASKS  (datasource: {inv_idx})")
    print("═" * 60)
    for task in INSIGHT_TASKS:
        all_results[f"insight_{task}"] = bench_insight_task(
            args.api, inv_idx, task, reps=args.reps
        )

    # ── Write report ────────────────────────────────────────────────────────────
    report = format_report(all_results, args.api, args.datasource, inv_idx, run_ts)
    out_path.write_text(report)

    print("\n" + "=" * 60)
    print("REPORT")
    print("=" * 60)
    print(report)
    print(f"\nFull report → {out_path}")


if __name__ == "__main__":
    main()
