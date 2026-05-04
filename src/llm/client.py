"""LLM client wrapping an OpenAI-compatible inference server (SGLang / Ollama / vLLM).

Supports both synchronous completion and streaming (for SSE endpoints).
Uses the openai Python SDK with a custom base_url pointing at the server.
"""
import os
import re
from typing import Generator

from openai import OpenAI
from openai import NotFoundError
from framework.commons.logger import logger
from framework.tracing import get_tracer

from src.config import Config

tracer = get_tracer()

# Qwen3 and other reasoning models may emit <think>...</think> blocks before
# the actual response. Strip them so downstream JSON parsers don't choke.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think_blocks(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


# Module-level cache of LLM-server endpoints we've discovered are unsupported
# (e.g. SGLang-specific routes when running against vLLM). Entries are added
# the first time a 404 is observed; cleared only by a process restart.
_UNSUPPORTED_ENDPOINTS: set[str] = set()

# Per-process cache of HuggingFace model config.json values, keyed by
# model id. Populated lazily on first call to ``_kv_bytes_per_token``.
_MODEL_CONFIG_CACHE: dict[str, dict] = {}

# Bytes per element for each KV-cache dtype vLLM supports.
_KV_DTYPE_BYTES = {
    "fp8":      1,
    "fp8_e5m2": 1,
    "fp8_e4m3": 1,
    "int8":     1,
    "fp16":     2,
    "bf16":     2,
    "bfloat16": 2,
    "auto":     2,   # vLLM uses fp16/bf16 here for non-fp8 deployments
    "float16":  2,
    "fp32":     4,
}


def _fetch_hf_config(model_id: str) -> dict:
    """Fetch and cache ``config.json`` for ``model_id`` from HuggingFace.

    No auth — works on public models, which is all we run today. Failures
    return ``{}`` so callers can fall back gracefully (no per-request VRAM
    on the UI is preferable to a crash).
    """
    if model_id in _MODEL_CONFIG_CACHE:
        return _MODEL_CONFIG_CACHE[model_id]
    import requests as _req
    cfg: dict = {}
    try:
        url = f"https://huggingface.co/{model_id}/resolve/main/config.json"
        r = _req.get(url, timeout=8)
        if r.ok:
            cfg = r.json()
    except Exception as e:
        logger.warning(f"[llm] HF config fetch failed for {model_id}: {e}")
    _MODEL_CONFIG_CACHE[model_id] = cfg
    return cfg


def _kv_bytes_per_token(model_id: str, kv_dtype: str | None) -> int | None:
    """Bytes consumed per token in the KV cache for ``model_id``.

    Formula::

        bytes_per_token = 2 (K + V) × num_hidden_layers
                          × num_key_value_heads × head_dim × dtype_bytes

    ``head_dim`` is ``hidden_size / num_attention_heads`` when not declared
    explicitly. Returns None if anything is missing — the UI will then
    just hide the per-request VRAM line.
    """
    cfg = _fetch_hf_config(model_id)
    if not cfg:
        return None
    try:
        num_layers      = int(cfg.get("num_hidden_layers", 0))
        num_kv_heads    = int(cfg.get("num_key_value_heads",
                                      cfg.get("num_attention_heads", 0)))
        if "head_dim" in cfg:
            head_dim = int(cfg["head_dim"])
        else:
            hidden     = int(cfg.get("hidden_size", 0))
            num_heads  = int(cfg.get("num_attention_heads", 0))
            head_dim   = hidden // num_heads if num_heads else 0
        dtype_bytes = _KV_DTYPE_BYTES.get((kv_dtype or "auto").lower(), 2)
        if not (num_layers and num_kv_heads and head_dim):
            return None
        return 2 * num_layers * num_kv_heads * head_dim * dtype_bytes
    except Exception as e:
        logger.warning(f"[llm] kv_bytes_per_token derivation failed: {e}")
        return None


class LLMClient:
    """Thin wrapper around the OpenAI SDK pointing at a local SGLang (or Ollama) instance."""

    def __init__(self):
        # SGLang/Ollama/vLLM all expose an OpenAI-compatible endpoint at /v1.
        # api_key is required by the SDK but not validated by local servers.
        self._client = OpenAI(
            base_url=Config.LLM_BASE_URL,
            api_key="EMPTY",
            timeout=Config.LLM_TIMEOUT,
        )
        self._model = None
        self._ctx_limit = 4096  # safe fallback
        self._temperature = Config.LLM_TEMPERATURE

        self._discover_model()

    @property
    def model_name(self) -> str:
        return self._model or "unknown"

    def _discover_model(self):
        """Query GET /v1/models (OpenAI-standard) to find the active model and context window.

        Works with SGLang, vLLM, and Ollama — all expose this endpoint.
        SGLang additionally includes max_model_len in the model metadata.
        """
        import requests
        try:
            resp = requests.get(f"{Config.LLM_BASE_URL}/models", timeout=10)
            resp.raise_for_status()
            models = resp.json().get("data", [])

            if not models:
                logger.error("[llm] No models found on inference server.")
                return

            configured = (Config.LLM_MODEL or "").strip()
            model_entry = None
            if configured:
                model_entry = next((m for m in models if m.get("id") == configured), None)
                if model_entry is None:
                    logger.warning(
                        f"[llm] Configured LLM_MODEL={configured!r} is not served by "
                        f"{Config.LLM_BASE_URL}; using server model list instead."
                    )

            # Prefer the configured model when it is actually served; otherwise
            # prefer instruct/chat variants; fall back to the first listed model.
            if model_entry is None:
                instruct = [m for m in models if "instruct" in m.get("id", "").lower()]
                model_entry = instruct[0] if instruct else models[0]
            self._model = model_entry["id"]

            # SGLang and vLLM expose max_model_len in the model object
            ctx = model_entry.get("max_model_len") or model_entry.get("context_window")
            if ctx:
                self._ctx_limit = int(ctx)

            logger.info(
                f"[llm] Discovered model: {self._model} "
                f"(context={self._ctx_limit} tokens, temperature={self._temperature}, "
                f"timeout={Config.LLM_TIMEOUT}s)"
            )

            # Propagate to Config so PromptBuilder can use the real context window
            if Config.LLM_INSIGHTS_CTX == 0:
                Config.LLM_INSIGHTS_CTX = self._ctx_limit
            if Config.LLM_CHAT_CTX == 0:
                Config.LLM_CHAT_CTX = min(self._ctx_limit, 16384)

        except Exception as e:
            logger.error(f"[llm] Model discovery failed: {e}")
            self._model = Config.LLM_MODEL or "unknown"
            if Config.LLM_INSIGHTS_CTX == 0: Config.LLM_INSIGHTS_CTX = 4096
            if Config.LLM_CHAT_CTX == 0:     Config.LLM_CHAT_CTX = 4096

    def _rediscover_after_not_found(self, error: Exception) -> bool:
        """Refresh model metadata after the server rejects our current model.

        This happens when the backend process starts before vLLM is ready and
        caches a fallback/configured model, then vLLM later comes up serving a
        different model. Return True when discovery found a different model.
        """
        old_model = self._model
        logger.warning(f"[llm] Model {old_model!r} was rejected by server: {error}. Re-discovering.")
        self._discover_model()
        changed = bool(self._model and self._model != old_model and self._model != "unknown")
        if changed:
            logger.info(f"[llm] Recovered model selection: {old_model!r} -> {self._model!r}")
        return changed

    # ── Synchronous completion ──────────────────────────────────────────────────

    def complete(self, messages: list[dict], system: str = "", num_ctx: int | None = None) -> str:
        """Send messages to the LLM and return the full response text."""
        import time
        from openai import APIConnectionError

        if "qwen3" in self._model.lower():
            system = (system.rstrip() + "\n/no_think") if system else "/no_think"
        full_messages = self._build_messages(messages, system)
        
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            with tracer.start_as_current_span("llm.complete") as span:
                span.set_attribute("llm.model", self._model)
                span.set_attribute("llm.messages_count", len(full_messages))
                span.set_attribute("llm.attempt", attempt + 1)
                try:
                    resp = self._client.chat.completions.create(
                        model=self._model,
                        messages=full_messages,
                        temperature=self._temperature,
                        top_p=Config.LLM_TOP_P,
                        stream=False,
                        timeout=Config.LLM_TIMEOUT,
                        extra_body={
                            "repetition_penalty": Config.LLM_REPETITION_PENALTY,
                        }
                    )
                    content = resp.choices[0].message.content or ""
                    content = _strip_think_blocks(content)
                    span.set_attribute("llm.response_length", len(content))
                    return content
                except APIConnectionError as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"[llm] Connection error on attempt {attempt + 1}, retrying in {retry_delay}s...: {e}")
                        time.sleep(retry_delay)
                        continue
                    logger.error(f"[llm] complete error after {max_retries} attempts: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise
                except NotFoundError as e:
                    if self._rediscover_after_not_found(e) and attempt < max_retries - 1:
                        full_messages = self._build_messages(messages, system)
                        continue
                    logger.error(f"[llm] complete model not found: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise
                except Exception as e:
                    logger.error(f"[llm] complete error: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise

    # ── Streaming ───────────────────────────────────────────────────────────────

    def stream(self, messages: list[dict], system: str = "", num_ctx: int | None = None) -> Generator[str, None, None]:
        """Stream the LLM response as text delta chunks."""
        import time
        from openai import APIConnectionError

        full_messages = self._build_messages(messages, system)
        
        max_retries = 3
        retry_delay = 2

        stream = None
        for attempt in range(max_retries):
            with tracer.start_as_current_span("llm.stream.setup") as span:
                span.set_attribute("llm.model", self._model)
                span.set_attribute("llm.messages_count", len(full_messages))
                span.set_attribute("llm.attempt", attempt + 1)
                try:
                    stream = self._client.chat.completions.create(
                        model=self._model,
                        messages=full_messages,
                        temperature=self._temperature,
                        top_p=Config.LLM_TOP_P,
                        stream=True,
                        timeout=Config.LLM_TIMEOUT,
                        extra_body={
                            "repetition_penalty": Config.LLM_REPETITION_PENALTY,
                        }
                    )
                    break
                except APIConnectionError as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"[llm] Connection error on stream attempt {attempt + 1}, retrying in {retry_delay}s...: {e}")
                        time.sleep(retry_delay)
                        continue
                    logger.error(f"[llm] stream error after {max_retries} attempts: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise
                except NotFoundError as e:
                    if self._rediscover_after_not_found(e) and attempt < max_retries - 1:
                        full_messages = self._build_messages(messages, system)
                        continue
                    logger.error(f"[llm] stream model not found: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise
                except Exception as e:
                    logger.error(f"[llm] stream error: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise
        
        # Yield outside the span so we don't hold a span open during streaming
        if stream:
            try:
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            except Exception as e:
                logger.error(f"[llm] stream iteration error: {e}", exc_info=True)
                raise

    # ── JSON structured output ──────────────────────────────────────────────────

    def complete_json(
        self,
        messages: list[dict],
        system: str = "",
        num_ctx: int | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Request a JSON response. Returns raw string — caller parses it."""
        import time
        from openai import APIConnectionError

        if "qwen3" in self._model.lower():
            system = (system.rstrip() + "\n/no_think") if system else "/no_think"
        full_messages = self._build_messages(messages, system)
        
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            with tracer.start_as_current_span("llm.complete_json") as span:
                span.set_attribute("llm.model", self._model)
                span.set_attribute("llm.messages_count", len(full_messages))
                span.set_attribute("llm.attempt", attempt + 1)
                try:
                    temp = temperature if temperature is not None else self._temperature
                    create_kwargs: dict = dict(
                        model=self._model,
                        messages=full_messages,
                        temperature=temp,
                        top_p=Config.LLM_TOP_P,
                        stream=False,
                        response_format={"type": "json_object"},
                        timeout=Config.LLM_TIMEOUT,
                        extra_body={
                            "repetition_penalty": Config.LLM_REPETITION_PENALTY,
                        }
                    )
                    if max_tokens is not None:
                        create_kwargs["max_tokens"] = max_tokens
                    resp = self._client.chat.completions.create(**create_kwargs)
                    content = resp.choices[0].message.content or "{}"
                    content = _strip_think_blocks(content)
                    span.set_attribute("llm.response_length", len(content))
                    return content
                except APIConnectionError as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"[llm] Connection error on attempt {attempt + 1}, retrying in {retry_delay}s...: {e}")
                        time.sleep(retry_delay)
                        continue
                    logger.error(f"[llm] complete_json error after {max_retries} attempts: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise
                except NotFoundError as e:
                    if self._rediscover_after_not_found(e) and attempt < max_retries - 1:
                        full_messages = self._build_messages(messages, system)
                        continue
                    logger.error(f"[llm] complete_json model not found: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise
                except Exception as e:
                    logger.error(f"[llm] complete_json error: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise

    # ── Model Information ──────────────────────────────────────────────────────

    def get_model_info(self) -> dict:
        """Fetch model metadata for the LLM stats UI.

        Tries the OpenAI-standard ``/v1/models`` (works on both vLLM and
        SGLang) plus SGLang's optional ``/model_info`` and ``/get_server_info``
        endpoints. Endpoints that return 404 are remembered for the rest of
        the process so we don't keep generating 404 log noise on a vLLM
        backend (vLLM doesn't implement the SGLang-specific ones).
        """
        import requests
        base = Config.LLM_BASE_URL.rstrip("/v1").rstrip("/")
        result: dict = {"model": self._model}

        # Per-process cache of endpoints we've discovered are unsupported.
        unsupported = _UNSUPPORTED_ENDPOINTS

        if "model_info" not in unsupported:
            try:
                r = requests.get(f"{base}/model_info", timeout=10)
                if r.status_code == 404:
                    unsupported.add("model_info")
                elif r.ok:
                    result.update(r.json())
            except Exception as e:
                logger.warning(f"[llm] /model_info unavailable: {e}")

        if "get_server_info" not in unsupported:
            try:
                r = requests.get(f"{base}/get_server_info", timeout=10)
                if r.status_code == 404:
                    unsupported.add("get_server_info")
                elif r.ok:
                    info = r.json()
                    for key in ("context_length", "max_running_requests",
                                "mem_fraction_static", "dtype", "quantization",
                                "kv_cache_dtype", "tp_size"):
                        if key in info:
                            result[key] = info[key]
            except Exception as e:
                logger.warning(f"[llm] /get_server_info unavailable: {e}")

        try:
            r = requests.get(f"{base}/v1/models", timeout=10)
            if r.ok:
                models = r.json().get("data", [])
                if models:
                    m = models[0]
                    served_model = m.get("id")
                    if served_model:
                        result["model"] = served_model
                        if self._model in (None, "unknown") or self._model != served_model:
                            self._model = served_model
                    result["max_model_len"] = m.get("max_model_len", result.get("context_length"))
                    # vLLM stops here; populate UI-friendly fallbacks so the
                    # stats card isn't half-empty when SGLang fields are absent.
                    result.setdefault("context_length", result.get("max_model_len"))
                    result.setdefault("served_model_name", served_model)
                    result["backend"] = "vllm" if "model_info" in unsupported else "sglang"
        except Exception:
            pass

        # When running under vLLM, scrape Prometheus /metrics and the model
        # name to populate fields the SGLang-native UI card expects (dtype,
        # quantization, kv_cache_dtype, mem_fraction_static, max_running_requests,
        # model_type). Without this, every field except Model + Context Window
        # shows "—" because vLLM doesn't expose /model_info or /get_server_info.
        if result.get("backend") == "vllm":
            try:
                r = requests.get(f"{base}/metrics", timeout=5)
                if r.ok:
                    text = r.text
                    # cache_config_info carries the runtime knobs
                    import re as _re
                    cfg_match = _re.search(r"vllm:cache_config_info\{([^}]+)\}", text)
                    if cfg_match:
                        labels = dict(_re.findall(r'(\w+)="([^"]*)"', cfg_match.group(1)))
                        if labels.get("cache_dtype"):
                            result["kv_cache_dtype"] = labels["cache_dtype"]
                        if labels.get("gpu_memory_utilization"):
                            try:
                                result["mem_fraction_static"] = float(
                                    labels["gpu_memory_utilization"])
                            except ValueError:
                                pass
                        if labels.get("block_size"):
                            result["kv_block_size"] = int(labels["block_size"])
                        if labels.get("num_gpu_blocks"):
                            result["kv_gpu_blocks"] = int(labels["num_gpu_blocks"])
                        if labels.get("enable_prefix_caching") in ("True", "true"):
                            result["enable_prefix_caching"] = True
            except Exception as e:
                logger.warning(f"[llm] vLLM /metrics scrape failed: {e}")

            # Concurrency limit is a vLLM start-up flag, not in Prometheus —
            # mirror it from our Config so the UI shows the right number.
            result.setdefault("max_running_requests", Config.VLLM_MAX_NUM_SEQS)

            # Quantization heuristic from the model name suffix. Cheap,
            # always right for our deployment, and avoids wiring another
            # env var for a value the model id already encodes.
            mid = (result.get("served_model_name") or self._model or "").upper()
            if "AWQ" in mid:
                result.setdefault("quantization", "awq_marlin")
            elif "GPTQ" in mid:
                result.setdefault("quantization", "gptq")
            elif "FP8" in mid:
                result.setdefault("quantization", "fp8")

            # vLLM is always half-precision compute (the AWQ kernel runs in
            # FP16); we expose this as the "Inference Type" field. Override-
            # safe via env if a future deploy uses bfloat16 or similar.
            result.setdefault("dtype", os.environ.get("VLLM_DTYPE", "float16"))

            # Architecture: derive from model name. vLLM logs the resolved
            # architecture but doesn't surface it via API; this mapping
            # covers the families we run today and falls back gracefully.
            arch_hints = {
                "QWEN3":     "Qwen3ForCausalLM",
                "QWEN2.5":   "Qwen2ForCausalLM",
                "QWEN2":     "Qwen2ForCausalLM",
                "QWEN":      "QwenForCausalLM",
                "LLAMA":     "LlamaForCausalLM",
                "MISTRAL":   "MistralForCausalLM",
                "GEMMA":     "GemmaForCausalLM",
            }
            if "model_type" not in result:
                for token, arch in arch_hints.items():
                    if token in mid:
                        result["model_type"] = arch
                        break

        if len(result) <= 1:
            return {"error": "Could not reach inference server", "model": self._model}

        return result

    def get_live_metrics(self) -> dict:
        """Return live runtime metrics from vLLM's Prometheus ``/metrics`` endpoint.

        Surfaces only the headline gauges/counters we care about for the
        Overview page — running/waiting requests, KV cache utilisation,
        prefix-cache hit rate, total tokens, and a derived "VRAM dedicated to
        KV cache" estimate from ``cache_config_info``. Best-effort: returns
        ``{"available": False}`` on a non-vLLM backend or any scrape failure.
        """
        import re
        import requests
        base = Config.LLM_BASE_URL.rstrip("/v1").rstrip("/")
        try:
            r = requests.get(f"{base}/metrics", timeout=5)
            if not r.ok:
                return {"available": False, "reason": f"HTTP {r.status_code}"}
            text = r.text
        except Exception as e:
            return {"available": False, "reason": str(e)}

        def _gauge(name: str) -> float | None:
            """Return the first numeric value for ``vllm:<name>{...}`` (any labels)."""
            m = re.search(rf"^vllm:{re.escape(name)}\{{[^}}]*\}}\s+([0-9eE.+\-]+)\s*$",
                          text, re.MULTILINE)
            return float(m.group(1)) if m else None

        def _config_label(key: str) -> str | None:
            """Pull ``key="..."`` out of the ``vllm:cache_config_info`` line.

            Requires a ``{`` or ``,`` boundary before the key so e.g. searching
            for ``block_size`` doesn't accidentally match ``_block_size_resolved``.
            """
            m = re.search(
                rf'vllm:cache_config_info\{{[^}}]*?[{{,]{re.escape(key)}="([^"]+)"',
                text,
            )
            return m.group(1) if m else None

        running   = _gauge("num_requests_running")
        waiting   = _gauge("num_requests_waiting")
        kv_perc   = _gauge("kv_cache_usage_perc")
        prompt_t  = _gauge("prompt_tokens_total")
        gen_t     = _gauge("generation_tokens_total")
        pcache_q  = _gauge("prefix_cache_queries_total")
        pcache_h  = _gauge("prefix_cache_hits_total")
        preempt   = _gauge("num_preemptions_total")

        # Derive KV-cache capacity from config: blocks × block_size × ~bytes/token.
        # bytes/token depends on model — we surface the raw block stats and let
        # the UI present them; "VRAM" is approximated only when configured.
        num_gpu_blocks = _config_label("num_gpu_blocks")
        block_size     = _config_label("block_size")
        gpu_mem_util   = _config_label("gpu_memory_utilization")
        kv_dtype       = _config_label("cache_dtype")

        def _safe_int(s):
            """vLLM emits the string ``"None"`` for unset numeric labels."""
            if s in (None, "", "None"):
                return None
            try:
                return int(s)
            except (TypeError, ValueError):
                return None

        def _safe_float(s):
            if s in (None, "", "None"):
                return None
            try:
                return float(s)
            except (TypeError, ValueError):
                return None

        num_gpu_blocks_i = _safe_int(num_gpu_blocks)
        block_size_i     = _safe_int(block_size)
        gpu_mem_util_f   = _safe_float(gpu_mem_util)
        kv_capacity_tokens = (
            num_gpu_blocks_i * block_size_i
            if num_gpu_blocks_i is not None and block_size_i is not None
            else None
        )

        prefix_hit_rate = None
        if pcache_q and pcache_q > 0 and pcache_h is not None:
            prefix_hit_rate = pcache_h / pcache_q

        # ── Per-request VRAM derivation ────────────────────────────────────
        # KV cache is the dominant per-request memory cost on vLLM. Convert
        # KV-tokens → bytes via the model's architectural shape:
        #
        #     bytes/token = 2 × layers × kv_heads × head_dim × dtype_bytes
        #
        # Then per-request VRAM = kv_tokens_used × bytes_per_token /
        # max(1, requests_running). If no requests are active, surface the
        # *theoretical* maximum share (total KV / max_running_requests) so
        # the panel still shows a meaningful number.
        kv_tokens_used = (
            int(kv_capacity_tokens * kv_perc)
            if (kv_capacity_tokens is not None and kv_perc is not None)
            else None
        )
        bytes_per_token = _kv_bytes_per_token(self._model, kv_dtype)
        kv_total_bytes = (
            kv_capacity_tokens * bytes_per_token
            if (kv_capacity_tokens is not None and bytes_per_token is not None)
            else None
        )
        kv_used_bytes = (
            kv_tokens_used * bytes_per_token
            if (kv_tokens_used is not None and bytes_per_token is not None)
            else None
        )
        running_i = int(running) if running is not None else None
        per_req_vram_bytes = None
        per_req_vram_basis = None
        if kv_used_bytes is not None and running_i and running_i > 0:
            per_req_vram_bytes = kv_used_bytes // running_i
            per_req_vram_basis = "actual"
        elif kv_total_bytes is not None:
            slots = max(1, Config.VLLM_MAX_NUM_SEQS)
            per_req_vram_bytes = kv_total_bytes // slots
            per_req_vram_basis = "theoretical"

        return {
            "available":              True,
            "backend":                "vllm",
            "requests_running":       running_i,
            "requests_waiting":       int(waiting)  if waiting  is not None else None,
            "kv_cache_usage_perc":    kv_perc,                 # 0..1
            "kv_cache_tokens_used":   kv_tokens_used,
            "kv_cache_capacity_tokens": kv_capacity_tokens,
            "kv_cache_dtype":         kv_dtype,
            "kv_cache_block_size":    block_size_i,
            "kv_cache_gpu_blocks":    num_gpu_blocks_i,
            "kv_total_bytes":         kv_total_bytes,
            "kv_used_bytes":          kv_used_bytes,
            "kv_bytes_per_token":     bytes_per_token,
            # Per-request VRAM: ``actual`` = derived from current KV usage
            # divided across in-flight requests; ``theoretical`` = total KV /
            # max concurrent slots. The UI labels them differently.
            "vram_per_request_bytes": per_req_vram_bytes,
            "vram_per_request_basis": per_req_vram_basis,
            "gpu_memory_utilization": gpu_mem_util_f,
            "prompt_tokens_total":    int(prompt_t) if prompt_t is not None else None,
            "generation_tokens_total": int(gen_t)   if gen_t    is not None else None,
            "prefix_cache_hit_rate":  prefix_hit_rate,
            "preemptions_total":      int(preempt) if preempt is not None else None,
        }

    def _legacy_passthrough(self) -> dict:
        return {}
        return result

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_messages(messages: list[dict], system: str) -> list[dict]:
        """Prepend system message if provided, then append conversation messages."""
        result = []
        if system:
            result.append({"role": "system", "content": system})
        result.extend(messages)
        return result


# Module-level singleton
_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    """Return the module-level LLMClient singleton."""
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
