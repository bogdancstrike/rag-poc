"""LLM client wrapping an OpenAI-compatible inference server (SGLang / Ollama / vLLM).

Supports both synchronous completion and streaming (for SSE endpoints).
Uses the openai Python SDK with a custom base_url pointing at the server.
"""
import re
from typing import Generator

from openai import OpenAI
from framework.commons.logger import logger
from framework.tracing import get_tracer

from src.config import Config

tracer = get_tracer()

# Qwen3 and other reasoning models may emit <think>...</think> blocks before
# the actual response. Strip them so downstream JSON parsers don't choke.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think_blocks(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


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

            # Prefer instruct/chat variants; fall back to the first listed model
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
            self._model = "Qwen/Qwen2.5-3B-Instruct"
            if Config.LLM_INSIGHTS_CTX == 0: Config.LLM_INSIGHTS_CTX = 4096
            if Config.LLM_CHAT_CTX == 0:     Config.LLM_CHAT_CTX = 4096

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
                except Exception as e:
                    logger.error(f"[llm] complete_json error: {e}", exc_info=True)
                    span.set_attribute("llm.error", str(e))
                    raise

    # ── Model Information ──────────────────────────────────────────────────────

    def get_model_info(self) -> dict:
        """Fetch model metadata via the standard GET /v1/models/{id} endpoint.

        Works with SGLang, vLLM, and Ollama.
        """
        import requests
        try:
            url = f"{Config.LLM_BASE_URL}/models/{self._model}"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[llm] Failed to fetch model info: {e}")
            return {"error": str(e), "model": self._model}

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
