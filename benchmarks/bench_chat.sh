#!/usr/bin/env bash
# benchmarks/bench_chat.sh
#
# Measures RAG Chat throughput at 1 / 5 / 10 / 25 / 50 / 100 / 200 concurrent users.
# Chat goes DIRECT (not through Kafka) — this tests Flask + LLM streaming capacity.
#
# Usage:
#   ./benchmarks/bench_chat.sh [max_concurrency]
#
# Example:
#   ./benchmarks/bench_chat.sh 50          # test up to 50 concurrent users
#   BENCH_INDEX=qsint_docs_apac ./benchmarks/bench_chat.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/bench_lib.sh"

MAX_CONCURRENCY="${1:-200}"

CHAT_QUERIES=(
    "What are the main cyber threats identified in this dataset?"
    "Summarize the most recent disinformation campaigns."
    "Which threat actors appear most frequently?"
    "What geographic regions are most targeted?"
    "List any APT groups mentioned and their tactics."
    "Are there any supply chain attacks reported?"
    "What social media platforms are used for information operations?"
    "Identify trends in malware distribution methods."
    "Which documents mention election interference?"
    "What is the most common attack vector described?"
)

# ── Worker function (one chat request) ────────────────────────────────────────
chat_worker() {
    local worker_id="$1"
    local query_idx=$(( (worker_id - 1) % ${#CHAT_QUERIES[@]} ))
    local query="${CHAT_QUERIES[$query_idx]}"

    local body
    body=$(jq -nc \
        --arg ds "$INDEX" \
        --arg msg "$query" \
        '{datasource: $ds, message: $msg, top_k: 5}')

    timed_request "chat_w$worker_id" POST "$API/v1/chat" "$body"
}

# ── SSE streaming chat worker (counts to first token) ─────────────────────────
chat_stream_worker() {
    local worker_id="$1"
    local query_idx=$(( (worker_id - 1) % ${#CHAT_QUERIES[@]} ))
    local query="${CHAT_QUERIES[$query_idx]}"

    local body
    body=$(jq -nc \
        --arg ds "$INDEX" \
        --arg msg "$query" \
        '{datasource: $ds, message: $msg, top_k: 5}')

    local start_ns end_ns dur_ms http_code
    start_ns=$(date +%s%N)

    # Read the SSE stream — stop after 'done' event or 60s
    http_code=$(curl -s -o /tmp/bench_sse_$worker_id.txt \
        -w "%{http_code}" \
        -X POST "$API/v1/chat/stream" \
        -H "Content-Type: application/json" \
        --data "$body" \
        --max-time 90 \
        --no-buffer 2>/dev/null || echo "000")

    end_ns=$(date +%s%N)
    dur_ms=$(( (end_ns - start_ns) / 1000000 ))

    local result="ok"
    if [[ "$http_code" != "200" ]]; then
        result="err($http_code)"
    fi
    echo "chat_stream_w$worker_id $http_code $dur_ms $result"
}

# ── Run one concurrency level ──────────────────────────────────────────────────
run_level() {
    local concurrency="$1"
    local mode="${2:-sync}"
    local tmp_file
    tmp_file=$(mktemp /tmp/bench_chat_XXXXXX)

    echo -ne "  [${concurrency} users / ${mode}] ... "

    if [[ "$mode" == "stream" ]]; then
        export -f chat_stream_worker timed_request
        seq 1 "$concurrency" \
            | parallel --jobs "$concurrency" --line-buffer \
                chat_stream_worker {} \
            >> "$tmp_file" 2>/dev/null
    else
        export -f chat_worker timed_request
        seq 1 "$concurrency" \
            | parallel --jobs "$concurrency" --line-buffer \
                chat_worker {} \
            >> "$tmp_file" 2>/dev/null
    fi

    print_stats "$tmp_file" "${concurrency} concurrent chat (${mode})"

    local out="$RESULTS_DIR/chat_${mode}_c${concurrency}_${TIMESTAMP}.tsv"
    echo -e "worker\thttp_code\tduration_ms\tstatus" > "$out"
    awk '{print $1"\t"$2"\t"$3"\t"$4}' "$tmp_file" >> "$out"

    rm -f "$tmp_file"
}

# ── Main ───────────────────────────────────────────────────────────────────────
main() {
    require_tools
    echo -e "\n${BOLD}${CYAN}═══ RAG Chat Benchmark ═══${RESET}"
    echo -e "  API: $API"
    check_backend
    discover_index

    # Concurrency levels — skip any that exceed MAX_CONCURRENCY
    local levels=(1 5 10 25 50 100 200)

    echo -e "\n${BOLD}── Sync chat (POST /v1/chat) ──${RESET}"
    for c in "${levels[@]}"; do
        [[ $c -gt $MAX_CONCURRENCY ]] && break
        run_level "$c" "sync"
    done

    echo -e "\n${BOLD}── Streaming chat (POST /v1/chat/stream) ──${RESET}"
    for c in "${levels[@]}"; do
        [[ $c -gt $MAX_CONCURRENCY ]] && break
        run_level "$c" "stream"
    done

    echo -e "\n${GREEN}Results saved to: $RESULTS_DIR/${RESET}"
}

main "$@"
