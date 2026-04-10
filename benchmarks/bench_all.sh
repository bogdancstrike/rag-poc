#!/usr/bin/env bash
# benchmarks/bench_all.sh
#
# Master benchmark runner — runs chat, enrichment, and mixed workloads.
# Generates a single summary report at the end.
#
# Usage:
#   ./benchmarks/bench_all.sh [max_concurrency]
#
# Environment:
#   BENCH_API        — backend URL (default: http://localhost:5100/rag)
#   BENCH_INDEX      — Elasticsearch index (auto-discovered if not set)
#   BENCH_RESULTS_DIR — where to write TSV results (default: benchmarks/results/)
#
# Prerequisites:
#   sudo apt-get install -y parallel jq bc curl

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/bench_lib.sh"

MAX_CONCURRENCY="${1:-200}"
REPORT="$RESULTS_DIR/bench_summary_${TIMESTAMP}.txt"

separator() { echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }

main() {
    require_tools
    echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║         QSINT RAG — Full Benchmark Suite                     ║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════╝${RESET}"
    echo -e "  API      : $API"
    echo -e "  Max conc : $MAX_CONCURRENCY"
    echo -e "  Results  : $RESULTS_DIR"
    echo -e "  Timestamp: $TIMESTAMP"
    check_backend
    discover_index

    # ── System info ──────────────────────────────────────────────────────────
    echo -e "\n${BOLD}System info:${RESET}"
    echo -e "  CPU cores : $(nproc)"
    echo -e "  Mem total : $(free -h | awk '/^Mem:/{print $2}')"
    echo -e "  LLM_PARALLEL: $(curl -s "$API/health" | jq -r '.llm.model // "unknown"') (from health)"

    local suite_start suite_end
    suite_start=$(date +%s)

    # ── 1. Chat benchmark ─────────────────────────────────────────────────────
    separator
    echo -e "${BOLD}[1/3] RAG Chat Benchmark${RESET}"
    bash "$SCRIPT_DIR/bench_chat.sh" "$MAX_CONCURRENCY" 2>&1 | tee -a "$REPORT"

    # ── 2. Enrichment benchmark ───────────────────────────────────────────────
    separator
    echo -e "${BOLD}[2/3] Enrichment & Intelligence Benchmark${RESET}"
    bash "$SCRIPT_DIR/bench_enrichment.sh" "$MAX_CONCURRENCY" 2>&1 | tee -a "$REPORT"

    # ── 3. Mixed workload ─────────────────────────────────────────────────────
    separator
    echo -e "${BOLD}[3/3] Mixed Workload Benchmark${RESET}"
    bash "$SCRIPT_DIR/bench_mixed.sh" "$MAX_CONCURRENCY" 2>&1 | tee -a "$REPORT"

    suite_end=$(date +%s)
    local total_sec=$(( suite_end - suite_start ))

    separator
    echo -e "\n${BOLD}${GREEN}═══ Benchmark Complete ═══${RESET}"
    echo -e "  Total wall time : ${total_sec}s"
    echo -e "  Results dir     : $RESULTS_DIR"
    echo -e "  Summary report  : $REPORT"
    echo ""
    echo -e "${YELLOW}Tip: View TSV results with:${RESET}"
    echo -e "  column -t $RESULTS_DIR/*.tsv | less -S"
    echo ""
}

main "$@"
