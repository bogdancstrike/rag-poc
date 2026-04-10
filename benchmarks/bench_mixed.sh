#!/usr/bin/env bash
# benchmarks/bench_mixed.sh
#
# Mixed workload: simultaneous chat + enrichment + insight generation.
# Simulates real analyst usage: some users chatting while background
# Kafka workers process enrichment tasks.
#
# Concurrency configurations tested:
#   chat_users × enrich_users (total = chat + enrich)
#   e.g. 5×5=10, 10×10=20, 25×25=50, 50×50=100, 100×100=200
#
# Usage:
#   ./benchmarks/bench_mixed.sh [max_total_users]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/bench_lib.sh"

MAX_TOTAL="${1:-200}"

CHAT_QUERY="Identify the most active threat actors and their recent campaigns."
SAMPLE_TEXT="APT28 has been observed deploying spear-phishing attacks against \
NATO member organizations. Custom implants (X-Agent, Sofacy) used for lateral \
movement. CVE-2024-5678 exploited in initial access. C2 infrastructure: \
185.220.101.10, evil-domain.net. Operation timeline: Jan 2026 recon, \
Feb 2026 intrusion, Mar 2026 data exfiltration. Location: Brussels, Tallinn."

# ── Worker implementations ─────────────────────────────────────────────────────

mixed_chat_worker() {
    local worker_id="$1"
    local body
    body=$(jq -nc \
        --arg ds "$INDEX" \
        --arg msg "$CHAT_QUERY" \
        '{datasource: $ds, message: $msg, top_k: 5}')
    timed_request "chat_w${worker_id}" POST "$API/v1/chat" "$body"
}

mixed_enrich_worker() {
    local worker_id="$1"
    local doc_id="mixed-bench-$(date +%s)-${worker_id}-$$"
    local body
    body=$(jq -nc \
        --arg ds "$INDEX" \
        --arg id "$doc_id" \
        --arg txt "$SAMPLE_TEXT" \
        '{datasource: $ds, doc_id: $id, text: $txt, force: true}')
    timed_request "enrich_w${worker_id}" POST "$API/v1/documents/enrich" "$body"
}

mixed_insight_worker() {
    local worker_id="$1"
    timed_request "insight_w${worker_id}" GET "$API/v1/insights?datasource=${INDEX}"
}

# ── Run one mixed scenario ─────────────────────────────────────────────────────
run_mixed() {
    local chat_n="$1"
    local enrich_n="$2"
    local insight_n="${3:-0}"
    local total=$(( chat_n + enrich_n + insight_n ))

    local tmp_chat tmp_enrich tmp_insight
    tmp_chat=$(mktemp /tmp/bench_mixed_chat_XXXXXX)
    tmp_enrich=$(mktemp /tmp/bench_mixed_enrich_XXXXXX)
    tmp_insight=$(mktemp /tmp/bench_mixed_insight_XXXXXX)

    echo -e "\n${BOLD}── Mixed: ${chat_n} chat + ${enrich_n} enrich + ${insight_n} insight (total=${total}) ──${RESET}"

    export -f mixed_chat_worker mixed_enrich_worker mixed_insight_worker timed_request
    export API INDEX SAMPLE_TEXT CHAT_QUERY

    local wall_start wall_end wall_ms
    wall_start=$(date +%s%N)

    # Launch all three workloads in parallel (background)
    {
        seq 1 "$chat_n" \
            | parallel --jobs "$chat_n" --line-buffer \
                mixed_chat_worker {} \
            >> "$tmp_chat" 2>/dev/null
    } &
    local pid_chat=$!

    {
        seq 1 "$enrich_n" \
            | parallel --jobs "$enrich_n" --line-buffer \
                mixed_enrich_worker {} \
            >> "$tmp_enrich" 2>/dev/null
    } &
    local pid_enrich=$!

    if [[ $insight_n -gt 0 ]]; then
        {
            seq 1 "$insight_n" \
                | parallel --jobs "$insight_n" --line-buffer \
                    mixed_insight_worker {} \
                >> "$tmp_insight" 2>/dev/null
        } &
        local pid_insight=$!
        wait "$pid_chat" "$pid_enrich" "$pid_insight"
    else
        wait "$pid_chat" "$pid_enrich"
    fi

    wall_end=$(date +%s%N)
    wall_ms=$(( (wall_end - wall_start) / 1000000 ))

    print_stats "$tmp_chat"    "  Chat    (${chat_n} req)"
    print_stats "$tmp_enrich"  "  Enrich  (${enrich_n} req)"
    [[ $insight_n -gt 0 ]] && print_stats "$tmp_insight" "  Insight (${insight_n} req)"

    echo -e "  ${CYAN}Wall-clock total: ${wall_ms}ms${RESET}"

    # Save combined results
    local base="$RESULTS_DIR/mixed_c${total}_${TIMESTAMP}"
    cat "$tmp_chat"   | awk '{print "chat\t"$1"\t"$2"\t"$3"\t"$4}' > "${base}_chat.tsv"
    cat "$tmp_enrich" | awk '{print "enrich\t"$1"\t"$2"\t"$3"\t"$4}' > "${base}_enrich.tsv"
    [[ $insight_n -gt 0 ]] && cat "$tmp_insight" | awk '{print "insight\t"$1"\t"$2"\t"$3"\t"$4}' > "${base}_insight.tsv"

    rm -f "$tmp_chat" "$tmp_enrich" "$tmp_insight"
}

# ── Main ───────────────────────────────────────────────────────────────────────
main() {
    require_tools
    echo -e "\n${BOLD}${CYAN}═══ Mixed Workload Benchmark ═══${RESET}"
    echo -e "  API: $API"
    check_backend
    discover_index

    # Scenario matrix: (chat_users, enrich_users, insight_users)
    # Total users: 10, 20, 50, 100, 200
    declare -a SCENARIOS=(
        "1 1 0"       # 2 total  — baseline
        "5 5 0"       # 10 total
        "5 5 2"       # 12 total — with insight
        "10 10 0"     # 20 total
        "10 10 5"     # 25 total — with insight
        "25 25 0"     # 50 total
        "25 25 5"     # 55 total
        "50 50 0"     # 100 total
        "50 50 10"    # 110 total
        "100 100 0"   # 200 total
        "100 100 10"  # 210 total
    )

    for scenario in "${SCENARIOS[@]}"; do
        read -r chat_n enrich_n insight_n <<< "$scenario"
        local total=$(( chat_n + enrich_n + insight_n ))
        [[ $total -gt $MAX_TOTAL ]] && continue
        run_mixed "$chat_n" "$enrich_n" "$insight_n"
    done

    echo -e "\n${GREEN}All mixed benchmark results saved to: $RESULTS_DIR/${RESET}"
}

main "$@"
