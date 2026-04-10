#!/usr/bin/env bash
# benchmarks/bench_enrichment.sh
#
# Measures document enrichment and intelligence report throughput.
# These go through Kafka → LLM worker pool (bounded by LLM_PARALLEL).
#
# Concurrency levels: 1 / 5 / 10 / 25 / 50 / 100 / 200
#
# Usage:
#   ./benchmarks/bench_enrichment.sh [max_concurrency]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/bench_lib.sh"

MAX_CONCURRENCY="${1:-200}"

SAMPLE_TEXT="Intelligence report: APT29 has been identified conducting spear-phishing \
campaigns targeting government entities in Eastern Europe. The operation uses custom \
malware distributed via compromised email accounts. CVE-2024-1234 is being actively \
exploited. Domains observed: malicious-c2.ru, payload-delivery.xyz. \
IP addresses: 192.168.100.50, 10.20.30.40. \
Key entities: FSB, GRU Unit 74455, Ukraine CERT. \
Locations: Kyiv, Warsaw, Berlin. Events: March 2026 phishing wave, April 2026 data exfil."

# ── Workers ────────────────────────────────────────────────────────────────────

enrich_stream_worker() {
    local worker_id="$1"
    # Each worker uses a unique fake doc_id so they don't collide on the PK
    local doc_id="bench-doc-$(date +%s)-${worker_id}-$$"

    local body
    body=$(jq -nc \
        --arg ds "$INDEX" \
        --arg id "$doc_id" \
        --arg txt "$SAMPLE_TEXT" \
        '{datasource: $ds, doc_id: $id, text: $txt, force: true}')

    local start_ns end_ns dur_ms http_code
    start_ns=$(date +%s%N)

    # SSE stream — read until 'complete' or timeout
    local tmp_out="/tmp/bench_enrich_sse_$worker_id.txt"
    curl -s -X POST "$API/v1/documents/enrich/stream" \
        -H "Content-Type: application/json" \
        --data "$body" \
        --max-time 120 \
        --no-buffer \
        -o "$tmp_out" \
        -w "%{http_code}" 2>/dev/null > /tmp/bench_enrich_code_$worker_id.txt || true

    end_ns=$(date +%s%N)
    dur_ms=$(( (end_ns - start_ns) / 1000000 ))
    http_code=$(cat /tmp/bench_enrich_code_$worker_id.txt 2>/dev/null || echo "000")

    local result="ok"
    # Check if 'complete' event arrived
    if ! grep -q '"type":"complete"' "$tmp_out" 2>/dev/null; then
        result="no_complete($http_code)"
    fi
    rm -f "$tmp_out" "/tmp/bench_enrich_code_$worker_id.txt"

    echo "enrich_stream_w$worker_id $http_code $dur_ms $result"
}

enrich_async_worker() {
    local worker_id="$1"
    local doc_id="bench-async-doc-$(date +%s)-${worker_id}-$$"

    local body
    body=$(jq -nc \
        --arg ds "$INDEX" \
        --arg id "$doc_id" \
        --arg txt "$SAMPLE_TEXT" \
        '{datasource: $ds, doc_id: $id, text: $txt, force: true}')

    # POST enrich → expect 202 (queued via Kafka)
    timed_request "enrich_async_w$worker_id" POST "$API/v1/documents/enrich" "$body"
}

insight_trigger_worker() {
    local worker_id="$1"
    local ds="${INDEX}"

    # Trigger insight generation (queues coordinator via Kafka)
    timed_request "insight_trigger_w$worker_id" GET "$API/v1/insights?datasource=${ds}&force=true"
}

field_enrich_worker() {
    local worker_id="$1"
    local doc_id="bench-field-$(date +%s)-${worker_id}-$$"
    local fields=("sentiment" "classification" "summary" "entities" "iocs")
    local field="${fields[$(( (worker_id - 1) % ${#fields[@]} ))]}"

    local body
    body=$(jq -nc \
        --arg ds "$INDEX" \
        --arg id "$doc_id" \
        --arg txt "$SAMPLE_TEXT" \
        --arg f "$field" \
        '{datasource: $ds, doc_id: $id, text: $txt, field: $f}')

    timed_request "field_w$worker_id" POST "$API/v1/documents/enrich/field" "$body"
}

# ── Run one concurrency level ──────────────────────────────────────────────────
run_level() {
    local concurrency="$1"
    local worker_fn="$2"
    local label="$3"
    local tmp_file
    tmp_file=$(mktemp /tmp/bench_enrich_XXXXXX)

    echo -ne "  [${concurrency} users] $label ... "

    export -f "$worker_fn" timed_request
    export API INDEX SAMPLE_TEXT

    seq 1 "$concurrency" \
        | parallel --jobs "$concurrency" --line-buffer \
            "$worker_fn" {} \
        >> "$tmp_file" 2>/dev/null

    print_stats "$tmp_file" "${concurrency} × ${label}"

    local out="$RESULTS_DIR/${worker_fn}_c${concurrency}_${TIMESTAMP}.tsv"
    echo -e "worker\thttp_code\tduration_ms\tstatus" > "$out"
    awk '{print $1"\t"$2"\t"$3"\t"$4}' "$tmp_file" >> "$out"

    rm -f "$tmp_file"
}

# ── Main ───────────────────────────────────────────────────────────────────────
main() {
    require_tools
    echo -e "\n${BOLD}${CYAN}═══ Enrichment & Intelligence Benchmark ═══${RESET}"
    echo -e "  API: $API"
    check_backend
    discover_index

    local levels=(1 5 10 25 50 100 200)

    echo -e "\n${BOLD}── Async doc enrichment (POST /v1/documents/enrich → Kafka) ──${RESET}"
    for c in "${levels[@]}"; do
        [[ $c -gt $MAX_CONCURRENCY ]] && break
        run_level "$c" "enrich_async_worker" "async enrich enqueue"
    done

    echo -e "\n${BOLD}── SSE stream enrichment (POST /v1/documents/enrich/stream → inline) ──${RESET}"
    # Stream enrichment is heavy (LLM call inline) — cap at 25 by default
    local stream_max=$(( MAX_CONCURRENCY < 25 ? MAX_CONCURRENCY : 25 ))
    for c in "${levels[@]}"; do
        [[ $c -gt $stream_max ]] && break
        run_level "$c" "enrich_stream_worker" "SSE stream enrich"
    done

    echo -e "\n${BOLD}── Single-field enrichment (POST /v1/documents/enrich/field → Kafka) ──${RESET}"
    for c in "${levels[@]}"; do
        [[ $c -gt $MAX_CONCURRENCY ]] && break
        run_level "$c" "field_enrich_worker" "field enrich enqueue"
    done

    echo -e "\n${BOLD}── Insight generation trigger (GET /v1/insights → Kafka coordinator) ──${RESET}"
    for c in "${levels[@]}"; do
        [[ $c -gt $MAX_CONCURRENCY ]] && break
        run_level "$c" "insight_trigger_worker" "insight trigger"
    done

    echo -e "\n${GREEN}Results saved to: $RESULTS_DIR/${RESET}"
}

main "$@"
