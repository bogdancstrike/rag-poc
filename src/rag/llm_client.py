"""LLM client wrapping the OpenAI-compatible Ollama API.

Supports both synchronous completion and streaming (for SSE endpoints).
Uses the openai Python SDK with a custom base_url pointing at Ollama.
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
    """Thin wrapper around the OpenAI SDK pointing at a local Ollama instance."""

    def __init__(self):
        # Ollama exposes an OpenAI-compatible endpoint at /v1
        # api_key is required by the SDK but unused by Ollama
        self._client = OpenAI(
            base_url=Config.LLM_BASE_URL,
            api_key="ollama",  # dummy key — Ollama doesn't validate it
            timeout=Config.LLM_TIMEOUT,
        )
        self._model       = Config.LLM_MODEL
        self._max_tokens  = Config.LLM_MAX_TOKENS
        self._temperature = Config.LLM_TEMPERATURE

    # ── Synchronous completion ──────────────────────────────────────────────────

    def complete(self, messages: list[dict], system: str = "") -> str:
        """Send messages to the LLM and return the full response text.

        Args:
            messages: List of {'role': ..., 'content': ...} dicts.
            system:   Optional system prompt prepended as a system message.

        Returns:
            The assistant's reply as a plain string.
        """
        if "qwen3" in self._model.lower():
            system = (system.rstrip() + "\n/no_think") if system else "/no_think"
        full_messages = self._build_messages(messages, system)
        with tracer.start_as_current_span("llm.complete") as span:
            span.set_attribute("llm.model", self._model)
            span.set_attribute("llm.messages_count", len(full_messages))
            span.set_attribute("llm.max_tokens", self._max_tokens)
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    stream=False,
                )
                content = resp.choices[0].message.content or ""
                content = _strip_think_blocks(content)
                span.set_attribute("llm.response_length", len(content))
                return content
            except Exception as e:
                logger.error(f"[llm] complete error: {e}", exc_info=True)
                span.set_attribute("llm.error", str(e))
                raise

    # ── Streaming ───────────────────────────────────────────────────────────────

    def stream(self, messages: list[dict], system: str = "") -> Generator[str, None, None]:
        """Stream the LLM response as text delta chunks.

        Uses create(stream=True) which yields ChatCompletionChunk objects
        with choices[0].delta.content.

        Note: the caller (chat_stream_handler) wraps the generator in its own
        llm_span — this span covers the initial API call setup only.
        """
        full_messages = self._build_messages(messages, system)
        with tracer.start_as_current_span("llm.stream.setup") as span:
            span.set_attribute("llm.model", self._model)
            span.set_attribute("llm.messages_count", len(full_messages))
            try:
                stream = self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    stream=True,
                )
            except Exception as e:
                logger.error(f"[llm] stream error: {e}", exc_info=True)
                span.set_attribute("llm.error", str(e))
                raise
        # Yield outside the span so we don't hold a span open during streaming
        try:
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"[llm] stream error: {e}", exc_info=True)
            raise

    # ── JSON structured output ──────────────────────────────────────────────────

    def complete_json(self, messages: list[dict], system: str = "") -> str:
        """Request a JSON response. Returns raw string — caller parses it.

        Ollama respects the response_format param for models that support it.
        We ensure the system prompt is focused on JSON output.

        For Qwen3-series models: thinking mode is suppressed via both the
        /no_think system-prompt token (model-level, always works) and the
        options.think=false Ollama parameter (API-level, requires Ollama ≥0.6).
        """
        # /no_think suppresses the Qwen3 reasoning chain at the model level.
        # Only append it for Qwen3 models — Qwen2.5 has no thinking mode and the
        # token confuses it, causing empty {} responses.
        if "qwen3" in self._model.lower():
            system = (system.rstrip() + "\n/no_think") if system else "/no_think"
        full_messages = self._build_messages(messages, system)
        with tracer.start_as_current_span("llm.complete_json") as span:
            span.set_attribute("llm.model", self._model)
            span.set_attribute("llm.messages_count", len(full_messages))
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    max_tokens=Config.LLM_JSON_MAX_TOKENS,
                    temperature=0.0,
                    stream=False,
                    response_format={"type": "json_object"},
                    # num_ctx=8192 is plenty for enrichment prompts + JSON output
                    # and is much faster than 16K on small models.
                    extra_body={"options": {"num_ctx": 8192}},
                )
                content = resp.choices[0].message.content or "{}"
                # Strip any residual <think>...</think> blocks (Qwen3 / reasoning
                # models may still emit them depending on Ollama version).
                content = _strip_think_blocks(content)
                span.set_attribute("llm.response_length", len(content))
                return content
            except Exception as e:
                logger.error(f"[llm] complete_json error: {e}", exc_info=True)
                span.set_attribute("llm.error", str(e))
                raise

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
