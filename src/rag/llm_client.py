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
        self._model = None
        self._ctx_limit = 4096  # safe fallback
        self._temperature = Config.LLM_TEMPERATURE
        
        self._discover_model()

    @property
    def model_name(self) -> str:
        return self._model or "unknown"

    def _discover_model(self):
        """Query Ollama to find the active model and its context window."""
        import requests
        try:
            # 1. Find the model name
            tags_url = Config.LLM_BASE_URL.replace("/v1", "/api/tags")
            resp = requests.get(tags_url, timeout=5)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            
            if not models:
                logger.error("[llm] No models found on Ollama server.")
                return

            # Preference: use the one that was likely orchestrated or the most recent
            # (We look for qwen2.5:3b-instruct which we pull in docker-compose)
            orchestrated = [m["name"] for m in models if "instruct" in m["name"].lower()]
            self._model = orchestrated[0] if orchestrated else models[0]["name"]

            # 2. Find the context window
            info_url = Config.LLM_BASE_URL.replace("/v1", "/api/show")
            info_resp = requests.post(info_url, json={"name": self._model}, timeout=5)
            info_resp.raise_for_status()
            info = info_resp.json()
            
            # Parse num_ctx from modelfile: "PARAMETER num_ctx 65536"
            modelfile = info.get("modelfile", "")
            match = re.search(r"num_ctx\s+(\d+)", modelfile)
            if match:
                self._ctx_limit = int(match.group(1))
            
            logger.info(
                f"[llm] Dynamically discovered model: {self._model} "
                f"(Context: {self._ctx_limit} tokens, temperature={self._temperature}, "
                f"timeout={Config.LLM_TIMEOUT}s)"
            )
            
            # Update Config global so other modules (PromptBuilder) can use it
            if Config.LLM_INSIGHTS_CTX == 0:
                Config.LLM_INSIGHTS_CTX = self._ctx_limit
            if Config.LLM_CHAT_CTX == 0:
                Config.LLM_CHAT_CTX = min(self._ctx_limit, 16384)

        except Exception as e:
            logger.error(f"[llm] Dynamic discovery failed: {e}")
            # Fallback to a sensible default if discovery fails
            self._model = "qwen2.5:3b-instruct"
            if Config.LLM_INSIGHTS_CTX == 0: Config.LLM_INSIGHTS_CTX = 4096
            if Config.LLM_CHAT_CTX == 0:     Config.LLM_CHAT_CTX = 4096

    # ── Synchronous completion ──────────────────────────────────────────────────

    def complete(self, messages: list[dict], system: str = "", num_ctx: int | None = None) -> str:
        """Send messages to the LLM and return the full response text."""
        if "qwen3" in self._model.lower():
            system = (system.rstrip() + "\n/no_think") if system else "/no_think"
        full_messages = self._build_messages(messages, system)
        with tracer.start_as_current_span("llm.complete") as span:
            span.set_attribute("llm.model", self._model)
            span.set_attribute("llm.messages_count", len(full_messages))
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    temperature=self._temperature,
                    top_p=Config.LLM_TOP_P,
                    stream=False,
                    timeout=Config.LLM_TIMEOUT,
                    extra_body={
                        "repeat_penalty": Config.LLM_REPETITION_PENALTY,
                    }
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

    def stream(self, messages: list[dict], system: str = "", num_ctx: int | None = None) -> Generator[str, None, None]:
        """Stream the LLM response as text delta chunks."""
        full_messages = self._build_messages(messages, system)
        with tracer.start_as_current_span("llm.stream.setup") as span:
            span.set_attribute("llm.model", self._model)
            span.set_attribute("llm.messages_count", len(full_messages))
            try:
                stream = self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    temperature=self._temperature,
                    top_p=Config.LLM_TOP_P,
                    stream=True,
                    timeout=Config.LLM_TIMEOUT,
                    extra_body={
                        "repeat_penalty": Config.LLM_REPETITION_PENALTY,
                    }
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

    def complete_json(
        self,
        messages: list[dict],
        system: str = "",
        num_ctx: int | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Request a JSON response. Returns raw string — caller parses it."""
        if "qwen3" in self._model.lower():
            system = (system.rstrip() + "\n/no_think") if system else "/no_think"
        full_messages = self._build_messages(messages, system)
        with tracer.start_as_current_span("llm.complete_json") as span:
            span.set_attribute("llm.model", self._model)
            span.set_attribute("llm.messages_count", len(full_messages))
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
                        "repeat_penalty": Config.LLM_REPETITION_PENALTY,
                    }
                )
                if max_tokens is not None:
                    create_kwargs["max_tokens"] = max_tokens
                resp = self._client.chat.completions.create(**create_kwargs)
                content = resp.choices[0].message.content or "{}"
                content = _strip_think_blocks(content)
                span.set_attribute("llm.response_length", len(content))
                return content
            except Exception as e:
                logger.error(f"[llm] complete_json error: {e}", exc_info=True)
                span.set_attribute("llm.error", str(e))
                raise

    # ── Model Information ──────────────────────────────────────────────────────

    def get_model_info(self) -> dict:
        """Fetch detailed model information from Ollama's /api/show endpoint."""
        import requests
        try:
            # We use the base_url but need to call /api/show instead of /v1/chat/completions
            # base_url is usually http://localhost:11434/v1
            url = Config.LLM_BASE_URL.replace("/v1", "/api/show")
            resp = requests.post(url, json={"name": self._model}, timeout=10)
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
