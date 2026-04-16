#!/usr/bin/env bash
# deploy.sh — QSINT RAG platform deploy + start script
#
# Usage:
#   ./deploy.sh                         # start full stack (SGLang default)
#   ./deploy.sh --ollama                # use Ollama instead of SGLang
#   ./deploy.sh --model Qwen/Qwen2.5-7B-Instruct --context 65536
#   ./deploy.sh --quantization awq      # use AWQ quantized model (lower VRAM)
#   ./deploy.sh --hf-token hf_xxx       # authenticate with HuggingFace Hub
#   ./deploy.sh --infra-only            # start infra only (no LLM server)
#   ./deploy.sh --backend               # start/restart Python backend only
#   ./deploy.sh --stop                  # stop all containers
#   ./deploy.sh --status                # show service status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*"; }
section() { echo -e "\n${BOLD}═══ $* ═══${RESET}"; }

# ── Defaults (read from .env first, allow CLI overrides) ───────────────────────
source_env() {
  if [[ -f .env ]]; then
    # Export only defined, non-comment lines
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
}
source_env

MODEL="${LLM_MODEL:-Qwen/Qwen2.5-3B-Instruct}"
CONTEXT="${LLM_CONTEXT_LENGTH:-32768}"
QUANT=""           # awq | gptq | "" (none)
HF_TOKEN="${HF_TOKEN:-}"
SGLANG_PORT="${SGLANG_PORT:-30000}"
SGLANG_MEM="${SGLANG_MEM_FRACTION:-0.85}"
API_PORT="${API_PORT:-5100}"
LLM_PARALLEL="${LLM_PARALLEL:-10}"
USE_OLLAMA=false
INFRA_ONLY=false
BACKEND_ONLY=false
ACTION="start"

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --model|-m)         MODEL="$2";    shift 2 ;;
    --context|-c)       CONTEXT="$2";  shift 2 ;;
    --quantization|-q)  QUANT="$2";    shift 2 ;;
    --hf-token)         HF_TOKEN="$2"; shift 2 ;;
    --port|-p)          SGLANG_PORT="$2"; shift 2 ;;
    --mem-fraction)     SGLANG_MEM="$2"; shift 2 ;;
    --parallel)         LLM_PARALLEL="$2"; shift 2 ;;
    --ollama)           USE_OLLAMA=true; shift ;;
    --infra-only)       INFRA_ONLY=true; shift ;;
    --backend)          BACKEND_ONLY=true; ACTION="backend"; shift ;;
    --stop)             ACTION="stop"; shift ;;
    --status)           ACTION="status"; shift ;;
    --help|-h)
      echo "Usage: ./deploy.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --model MODEL          HuggingFace model ID (default: Qwen/Qwen2.5-3B-Instruct)"
      echo "                         For Ollama: use tag format, e.g. qwen2.5:3b-instruct"
      echo "  --context N            Context length in tokens (default: 32768)"
      echo "  --quantization TYPE    Quantization: awq, gptq, or empty for none"
      echo "  --hf-token TOKEN       HuggingFace API token (for gated models)"
      echo "  --port PORT            SGLang/Ollama port (default: 30000 / 11434)"
      echo "  --mem-fraction F       SGLang VRAM fraction for KV cache (default: 0.85)"
      echo "  --parallel N           Max concurrent LLM requests (default: 10)"
      echo "  --ollama               Use Ollama instead of SGLang"
      echo "  --infra-only           Start infrastructure only (no LLM server)"
      echo "  --backend              Restart Python backend only"
      echo "  --stop                 Stop all containers"
      echo "  --status               Show service status"
      echo ""
      echo "Model examples:"
      echo "  Qwen/Qwen2.5-3B-Instruct          (3B, BF16, ~6GB VRAM)"
      echo "  Qwen/Qwen2.5-3B-Instruct-AWQ      (3B, INT4, ~2GB VRAM)"
      echo "  Qwen/Qwen2.5-7B-Instruct           (7B, BF16, ~15GB VRAM)"
      echo "  Qwen/Qwen2.5-7B-Instruct-AWQ       (7B, INT4, ~5GB VRAM)"
      exit 0
      ;;
    *) error "Unknown argument: $1"; exit 1 ;;
  esac
done

# ── Auto-select AWQ variant if --quantization awq and model doesn't include it ──
if [[ "$QUANT" == "awq" && "$MODEL" != *-AWQ* && "$MODEL" != *-awq* ]]; then
  MODEL="${MODEL}-AWQ"
  info "AWQ selected — using model: $MODEL"
fi

# ── Actions ────────────────────────────────────────────────────────────────────

do_status() {
  section "Service Status"
  docker compose ps 2>/dev/null || true
  if $USE_OLLAMA; then
    docker compose -f docker-compose-ollama.yml ps 2>/dev/null || true
  fi
  echo ""
  if pgrep -f "python main.py" > /dev/null 2>&1; then
    success "Backend running (PID: $(pgrep -f 'python main.py' | head -1))"
  else
    warn "Backend not running"
  fi
}

do_stop() {
  section "Stopping Services"
  docker compose down --remove-orphans 2>/dev/null || true
  docker compose -f docker-compose-ollama.yml down --remove-orphans 2>/dev/null || true
  pkill -f "python main.py" 2>/dev/null && success "Backend stopped" || true
}

start_backend() {
  section "Starting Python Backend"
  # Kill existing instance
  pkill -f "python main.py" 2>/dev/null || true

  # Write SGLang/Ollama-specific settings to .env if overridden by CLI args
  if [[ "$USE_OLLAMA" == "false" ]]; then
    LLM_URL="http://localhost:${SGLANG_PORT}/v1"
  else
    LLM_URL="http://localhost:${OLLAMA_PORT:-11434}/v1"
  fi

  # Patch LLM_BASE_URL in .env for this run (non-destructive sed replacement)
  if grep -q "^LLM_BASE_URL=" .env 2>/dev/null; then
    sed -i "s|^LLM_BASE_URL=.*|LLM_BASE_URL=${LLM_URL}|" .env
    info "Updated LLM_BASE_URL → ${LLM_URL}"
  fi

  info "Launching backend on port ${API_PORT}…"
  nohup .venv/bin/python main.py > /tmp/qsint-rag-backend.log 2>&1 &
  BACKEND_PID=$!
  echo "$BACKEND_PID" > /tmp/qsint-rag-backend.pid

  # Wait up to 15s for the API to respond
  for i in $(seq 1 15); do
    if curl -sf "http://localhost:${API_PORT}/rag/health" > /dev/null 2>&1; then
      success "Backend started (PID: ${BACKEND_PID}) — http://localhost:${API_PORT}/rag"
      return 0
    fi
    sleep 1
  done
  warn "Backend may still be starting. Check: tail -f /tmp/qsint-rag-backend.log"
}

# ── Handle non-start actions ───────────────────────────────────────────────────
case "$ACTION" in
  stop)   do_stop;   exit 0 ;;
  status) do_status; exit 0 ;;
  backend) start_backend; exit 0 ;;
esac

# ── Pre-flight checks ──────────────────────────────────────────────────────────
section "Pre-flight Checks"

# Docker
if ! command -v docker &> /dev/null; then
  error "Docker not found. Install Docker: https://docs.docker.com/get-docker/"
  exit 1
fi
success "Docker: $(docker --version | cut -d' ' -f3 | tr -d ',')"

# Docker Compose
if ! docker compose version &> /dev/null; then
  error "Docker Compose v2 not found. Update Docker or install the plugin."
  exit 1
fi
success "Docker Compose: $(docker compose version --short)"

# GPU (required for SGLang; optional for Ollama CPU)
if ! $USE_OLLAMA; then
  if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader | head -1)
    success "GPU: ${GPU_NAME} (${GPU_VRAM})"
  else
    warn "nvidia-smi not found — SGLang will run on CPU (slow). Use --ollama for Ollama."
  fi

  # nvidia-container-toolkit
  if ! docker info 2>/dev/null | grep -q "Runtimes.*nvidia"; then
    warn "nvidia-container-toolkit may not be installed."
    warn "Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
  else
    success "nvidia-container-toolkit: present"
  fi
fi

# Python venv
if [[ ! -f .venv/bin/python ]]; then
  warn ".venv not found — backend will not be started automatically."
  warn "Create it with: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  NO_BACKEND=true
else
  NO_BACKEND=false
  success "Python venv: .venv"
fi

# ── Export runtime env vars ────────────────────────────────────────────────────
export LLM_MODEL="$MODEL"
export LLM_CONTEXT_LENGTH="$CONTEXT"
export SGLANG_PORT="$SGLANG_PORT"
export SGLANG_MEM_FRACTION="$SGLANG_MEM"
export LLM_PARALLEL="$LLM_PARALLEL"
[[ -n "$HF_TOKEN" ]] && export HF_TOKEN

# ── Start infrastructure ───────────────────────────────────────────────────────
section "Starting Infrastructure"
info "Starting: postgres, elasticsearch, kafka, redis, jaeger, kafka-ui, kibana, pgadmin…"

INFRA_SERVICES="postgres elasticsearch kafka kafka-ui redis jaeger pgadmin kibana"
docker compose up -d $INFRA_SERVICES

# Wait for critical services
info "Waiting for Postgres…"
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-qf}" -d "${POSTGRES_DB:-qsint_rag}" > /dev/null 2>&1; do
  sleep 1
done
success "Postgres ready"

info "Waiting for Elasticsearch…"
until curl -sf "http://localhost:${ES_PORT:-9200}/_cluster/health" | grep -qE '"status":"(green|yellow)"' > /dev/null 2>&1; do
  sleep 2
done
success "Elasticsearch ready"

info "Waiting for Kafka…"
until docker compose exec -T kafka kafka-topics --bootstrap-server localhost:9092 --list > /dev/null 2>&1; do
  sleep 2
done
success "Kafka ready"

if $INFRA_ONLY; then
  success "Infrastructure started. Skipping LLM server (--infra-only)."
  do_status
  exit 0
fi

# ── Start LLM server ───────────────────────────────────────────────────────────
if $USE_OLLAMA; then
  section "Starting Ollama"
  info "Using Ollama with model: ${MODEL}"
  docker compose -f docker-compose-ollama.yml up -d ollama
  info "Waiting for Ollama…"
  until docker compose -f docker-compose-ollama.yml exec -T ollama ollama list > /dev/null 2>&1; do
    sleep 2
  done
  success "Ollama ready"
  info "Pulling model: ${MODEL}…"
  docker compose -f docker-compose-ollama.yml up ollama-pull-model
  success "Ollama model ready: ${MODEL}"
  LLM_URL="http://localhost:${OLLAMA_PORT:-11434}/v1"
else
  section "Starting SGLang"
  info "Model:        ${MODEL}"
  info "Context:      ${CONTEXT} tokens"
  info "VRAM budget:  $(echo "$SGLANG_MEM * 100" | bc 2>/dev/null || echo "${SGLANG_MEM}")%"
  [[ -n "$QUANT" ]] && info "Quantization: ${QUANT}"
  [[ -n "$HF_TOKEN" ]] && info "HF_TOKEN:     set"
  echo ""
  info "Starting container (model downloads on first run ~5-10 min)…"
  docker compose up -d sglang

  info "Waiting for SGLang to be healthy (this may take a few minutes)…"
  ELAPSED=0
  until docker compose exec -T sglang curl -sf http://localhost:30000/health > /dev/null 2>&1; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [[ $ELAPSED -gt 600 ]]; then
      error "SGLang did not become healthy within 10 minutes."
      error "Check logs: docker compose logs sglang"
      exit 1
    fi
    if [[ $((ELAPSED % 30)) -eq 0 ]]; then
      info "Still waiting… (${ELAPSED}s elapsed)"
    fi
  done
  success "SGLang ready — http://localhost:${SGLANG_PORT}/v1"
  LLM_URL="http://localhost:${SGLANG_PORT}/v1"

  # Show which model was loaded
  MODEL_ID=$(curl -sf "http://localhost:${SGLANG_PORT}/v1/models" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null || echo "$MODEL")
  CTX_LOADED=$(curl -sf "http://localhost:${SGLANG_PORT}/v1/models" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0].get('max_model_len','?'))" 2>/dev/null || echo "$CONTEXT")
  success "Loaded:       ${MODEL_ID} (context: ${CTX_LOADED} tokens)"
fi

# ── Update .env with active LLM_BASE_URL ──────────────────────────────────────
if grep -q "^LLM_BASE_URL=" .env 2>/dev/null; then
  sed -i "s|^LLM_BASE_URL=.*|LLM_BASE_URL=${LLM_URL}|" .env
  success "LLM_BASE_URL → ${LLM_URL}"
fi

# ── Download Embedding Model ──────────────────────────────────────────────────
if [[ "$NO_BACKEND" == "false" ]]; then
  section "Embedding Model"
  EMBED_MODEL_NAME=$(.venv/bin/python -c "from src.config import Config; print(Config.EMBED_MODEL)")
  EMBED_CACHE=$(.venv/bin/python -c "from src.config import Config; print(Config.EMBED_CACHE_DIR)")
  
  info "Checking/Downloading ${EMBED_MODEL_NAME}..."
  .venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${EMBED_MODEL_NAME}', cache_dir='${EMBED_CACHE}')"
  success "Embedding model ready"
fi

# ── Start Python backend ───────────────────────────────────────────────────────
if [[ "$NO_BACKEND" == "false" ]]; then
  start_backend
fi

# ── Summary ────────────────────────────────────────────────────────────────────
section "Platform Ready"
echo ""
echo -e "  ${BOLD}API${RESET}           http://localhost:${API_PORT}/rag"
echo -e "  ${BOLD}LLM${RESET}           ${LLM_URL}"
echo -e "  ${BOLD}Elasticsearch${RESET} http://localhost:${ES_PORT:-9200}"
echo -e "  ${BOLD}Kafka UI${RESET}      http://localhost:${KAFKA_UI_PORT:-8090}"
echo -e "  ${BOLD}Jaeger${RESET}        http://localhost:${JAEGER_UI_PORT:-16686}"
echo -e "  ${BOLD}Kibana${RESET}        http://localhost:${KIBANA_PORT:-5601}"
echo -e "  ${BOLD}pgAdmin${RESET}       http://localhost:5050"
echo -e "  ${BOLD}Backend log${RESET}   tail -f /tmp/qsint-rag-backend.log"
echo ""
success "Deploy complete."
