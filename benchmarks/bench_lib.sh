#!/usr/bin/env bash
# benchmarks/bench_lib.sh — shared helpers sourced by all benchmark scripts

API="${BENCH_API:-http://localhost:5100/rag}"
INDEX="${BENCH_INDEX:-qsint_docs_europe}"
RESULTS_DIR="${BENCH_RESULTS_DIR:-$(dirname "$0")/results}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; RESET='\033[0m'

# ── Helpers ────────────────────────────────────────────────────────────────────

require_tools() {
    local missing=()
    for t in curl jq parallel bc; do
        command -v "$t" &>/dev/null || missing+=("$t")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}Missing tools: ${missing[*]}${RESET}"
        echo "  Ubuntu/Debian: sudo apt-get install -y curl jq parallel bc"
        exit 1
    fi
}

check_backend() {
    local url="$API/health"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null)
    if [[ "$code" != "200" ]]; then
        echo -e "${RED}Backend not reachable at $API (HTTP $code)${RESET}"
        echo "  Start with: python main.py"
        exit 1
    fi
    echo -e "${GREEN}Backend OK — $API${RESET}"
}

# Discover a working index from the backend; fall back to BENCH_INDEX
discover_index() {
    local indices
    indices=$(curl -s --max-time 5 "$API/v1/datasource/indices" 2>/dev/null | jq -r '.indices[0]' 2>/dev/null)
    if [[ -n "$indices" && "$indices" != "null" ]]; then
        INDEX="$indices"
    fi
    echo -e "  Using index: ${CYAN}$INDEX${RESET}"
}

# Discover a document ID that has text from the index
discover_doc_id() {
    DOC_ID=$(curl -s --max-time 10 "$API/v1/documents?datasource=$INDEX&limit=1" 2>/dev/null \
        | jq -r '.documents[0].id // .docs[0].id // empty' 2>/dev/null)
    if [[ -z "$DOC_ID" ]]; then
        DOC_ID="benchmark-doc-$(date +%s)"
    fi
    DOC_TEXT=$(curl -s --max-time 10 "$API/v1/documents?datasource=$INDEX&limit=1" 2>/dev/null \
        | jq -r '.documents[0].text // .docs[0].text // "Sample benchmark document for intelligence analysis."' 2>/dev/null \
        | head -c 2000)
    echo -e "  Using doc: ${CYAN}$DOC_ID${RESET}"
}

mkdir -p "$RESULTS_DIR"

# ── Per-request timing helper ──────────────────────────────────────────────────
# Writes: <user_n> <http_code> <duration_ms> <ok|err>   to a temp file
# Usage: timed_request <label> <method> <url> [body_json]
timed_request() {
    local label="$1" method="$2" url="$3" body="${4:-}"
    local start_ns end_ns dur_ms http_code result

    start_ns=$(date +%s%N)
    if [[ -n "$body" ]]; then
        http_code=$(curl -s -o /dev/null -w "%{http_code}" \
            -X "$method" "$url" \
            -H "Content-Type: application/json" \
            --data "$body" \
            --max-time 120 2>/dev/null)
    else
        http_code=$(curl -s -o /dev/null -w "%{http_code}" \
            -X "$method" "$url" \
            --max-time 120 2>/dev/null)
    fi
    end_ns=$(date +%s%N)
    dur_ms=$(( (end_ns - start_ns) / 1000000 ))

    if [[ "$http_code" == "200" || "$http_code" == "202" ]]; then
        result="ok"
    else
        result="err($http_code)"
    fi

    echo "$label $http_code ${dur_ms} $result"
}

# ── Statistics from a results file ─────────────────────────────────────────────
# File format: one line per request: <label> <code> <ms> <ok|err>
print_stats() {
    local file="$1" title="$2"
    local count ok_count err_count min_ms max_ms avg_ms p50 p95 p99

    count=$(wc -l < "$file")
    ok_count=$(grep -c " ok$" "$file" 2>/dev/null || echo 0)
    err_count=$(( count - ok_count ))

    # Extract ms column
    local ms_values
    ms_values=$(awk '{print $3}' "$file" | sort -n)
    min_ms=$(echo "$ms_values" | head -1)
    max_ms=$(echo "$ms_values" | tail -1)
    avg_ms=$(echo "$ms_values" | awk '{s+=$1}END{printf "%.0f", s/NR}')
    p50=$(echo "$ms_values" | awk "NR==int($count*0.50+0.5){print}")
    p95=$(echo "$ms_values" | awk "NR==int($count*0.95+0.5){print}")
    p99=$(echo "$ms_values" | awk "NR==int($count*0.99+0.5){print}")

    echo -e ""
    echo -e "${BOLD}  ── $title ──${RESET}"
    echo -e "  Requests : $count  (OK=$ok_count  ERR=$err_count)"
    echo -e "  Latency  : min=${min_ms}ms  avg=${avg_ms}ms  max=${max_ms}ms"
    echo -e "  Percentile: p50=${p50}ms  p95=${p95}ms  p99=${p99}ms"

    if [[ $err_count -gt 0 ]]; then
        echo -e "  ${RED}Errors: $(grep -v " ok$" "$file" | head -5)${RESET}"
    fi
}

# Convenience: run N parallel jobs of a function, collect into a tmp file
# Usage: run_parallel <concurrency> <function_name> [extra_args...]
# The function is called as: <function_name> <worker_index> [extra_args...]
run_parallel_workers() {
    local concurrency="$1"
    local fn="$2"
    shift 2
    local extra_args=("$@")

    export -f "$fn" timed_request
    export API INDEX DOC_ID DOC_TEXT

    seq 1 "$concurrency" \
        | parallel --jobs "$concurrency" --line-buffer \
            "$fn" {} "${extra_args[@]}"
}
