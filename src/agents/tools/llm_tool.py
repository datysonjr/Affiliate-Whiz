"""LLM Tool - Provider-agnostic interface for large language model interactions.

This module provides a unified interface for interacting with various LLM providers
(OpenAI, Anthropic, local models, etc.) with built-in token tracking, fallback
support, and common NLP operations like summarization, classification, and
structured extraction.
"""

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LLMTool:
    """Provider-agnostic LLM interface with token tracking and fallback support.

    Supports configuring a primary and fallback provider so that requests
    automatically retry against the fallback when the primary is unavailable
    or rate-limited.

    Config keys:
        primary_provider (str): Name of the primary LLM provider
            (e.g. "openai", "anthropic").
        primary_model (str): Model identifier for the primary provider.
        primary_api_key (str): API key for the primary provider.
        primary_base_url (str, optional): Custom API base URL for the primary provider.
        fallback_provider (str, optional): Name of the fallback LLM provider.
        fallback_model (str, optional): Model identifier for the fallback provider.
        fallback_api_key (str, optional): API key for the fallback provider.
        fallback_base_url (str, optional): Custom API base URL for the fallback provider.
        default_max_tokens (int): Default maximum tokens for generation (default 1024).
        temperature (float): Default sampling temperature (default 0.7).
        timeout (int): Request timeout in seconds (default 60).
        retry_attempts (int): Number of retries before switching to fallback (default 2).
        retry_delay (float): Delay between retries in seconds (default 1.0).
    """

    SUPPORTED_PROVIDERS = ("anthropic", "openai")

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

        # Primary provider settings
        self.primary_provider: str = config.get("primary_provider", "anthropic")
        self.primary_model: str = config.get(
            "primary_model", "claude-sonnet-4-20250514"
        )
        self.primary_api_key: str = config.get("primary_api_key", "")
        self.primary_base_url: Optional[str] = config.get("primary_base_url")

        # Fallback provider settings
        self.fallback_provider: Optional[str] = config.get("fallback_provider")
        self.fallback_model: Optional[str] = config.get("fallback_model")
        self.fallback_api_key: Optional[str] = config.get("fallback_api_key")
        self.fallback_base_url: Optional[str] = config.get("fallback_base_url")

        # Generation defaults
        self.default_max_tokens: int = config.get("default_max_tokens", 1024)
        self.temperature: float = config.get("temperature", 0.7)
        self.timeout: int = config.get("timeout", 60)
        self.retry_attempts: int = config.get("retry_attempts", 2)
        self.retry_delay: float = config.get("retry_delay", 1.0)

        # Token usage tracking
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._total_requests: int = 0
        self._failed_requests: int = 0
        self._fallback_requests: int = 0

        # Provider client placeholders (initialized lazily)
        self._primary_client: Any = None
        self._fallback_client: Any = None

        logger.info(
            "LLMTool initialized with primary_provider=%s, model=%s, fallback=%s",
            self.primary_provider,
            self.primary_model,
            self.fallback_provider or "none",
        )

    # ------------------------------------------------------------------
    # Provider client management
    # ------------------------------------------------------------------

    def _get_primary_client(self) -> Any:
        if self._primary_client is None:
            self._primary_client = self._init_client(
                provider=self.primary_provider,
                model=self.primary_model,
                api_key=self.primary_api_key,
                base_url=self.primary_base_url,
            )
        return self._primary_client

    def _get_fallback_client(self) -> Any:
        if self._fallback_client is None and self.fallback_provider:
            self._fallback_client = self._init_client(
                provider=self.fallback_provider,
                model=self.fallback_model or "",
                api_key=self.fallback_api_key or "",
                base_url=self.fallback_base_url,
            )
        return self._fallback_client

    def _init_client(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
    ) -> Any:
        """Initialize an LLM provider client.

        Args:
            provider: Provider name ("openai" or "anthropic").
            model: Model identifier string.
            api_key: Authentication key for the provider API.
            base_url: Optional custom base URL for the API.

        Returns:
            An initialized provider client object.

        Raises:
            ValueError: If the provider is not supported.
        """
        logger.debug("Initializing %s client for model %s", provider, model)

        if provider == "anthropic":
            import anthropic

            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return anthropic.Anthropic(**kwargs)

        if provider == "openai":
            import openai

            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return openai.OpenAI(**kwargs)

        raise ValueError(
            f"Unsupported provider '{provider}'. Supported: {self.SUPPORTED_PROVIDERS}"
        )

    # ------------------------------------------------------------------
    # Internal request handling
    # ------------------------------------------------------------------

    def _call_anthropic(
        self,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Send a request to the Anthropic Messages API."""
        system_msg = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                api_messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = client.messages.create(**kwargs)

        content = ""
        if response.content:
            content = response.content[0].text

        prompt_tokens = getattr(response.usage, "input_tokens", 0)
        completion_tokens = getattr(response.usage, "output_tokens", 0)

        return {
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "provider": "anthropic",
            "model": model,
        }

    def _call_openai(
        self,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Send a request to the OpenAI Chat Completions API."""
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""

        prompt_tokens = 0
        completion_tokens = 0
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens or 0
            completion_tokens = response.usage.completion_tokens or 0

        return {
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "provider": "openai",
            "model": model,
        }

    def _dispatch_call(
        self,
        provider: str,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Dispatch an API call to the correct provider handler."""
        if provider == "anthropic":
            return self._call_anthropic(
                client, model, messages, max_tokens, temperature
            )
        if provider == "openai":
            return self._call_openai(client, model, messages, max_tokens, temperature)
        raise ValueError(f"Cannot dispatch to unknown provider: {provider}")

    def _call_provider(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: Optional[float] = None,
        provider_override: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send a request to an LLM provider with retry + fallback.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            max_tokens: Maximum number of tokens to generate.
            temperature: Sampling temperature override.
            provider_override: Force "primary" or "fallback".

        Returns:
            Normalized response dict with content, token counts, provider, model.

        Raises:
            RuntimeError: If all providers fail after exhausting retries.
        """
        temperature = temperature if temperature is not None else self.temperature
        last_error: Optional[Exception] = None

        # Try primary provider
        if provider_override != "fallback":
            for attempt in range(1, self.retry_attempts + 1):
                try:
                    logger.debug(
                        "Primary provider attempt %d/%d",
                        attempt,
                        self.retry_attempts,
                    )
                    self._total_requests += 1
                    client = self._get_primary_client()
                    return self._dispatch_call(
                        self.primary_provider,
                        client,
                        self.primary_model,
                        messages,
                        max_tokens,
                        temperature,
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Primary provider attempt %d failed: %s", attempt, exc
                    )
                    if attempt < self.retry_attempts:
                        time.sleep(self.retry_delay)

        # Try fallback provider
        if self.fallback_provider and provider_override != "primary":
            try:
                logger.info("Falling back to %s", self.fallback_provider)
                self._fallback_requests += 1
                self._total_requests += 1
                client = self._get_fallback_client()
                return self._dispatch_call(
                    self.fallback_provider,
                    client,
                    self.fallback_model or "",
                    messages,
                    max_tokens,
                    temperature,
                )
            except Exception as exc:
                last_error = exc
                logger.error("Fallback provider also failed: %s", exc)

        self._failed_requests += 1
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def _track_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self._total_prompt_tokens += prompt_tokens
        self._total_completion_tokens += completion_tokens
        logger.debug(
            "Token usage: prompt=%d, completion=%d, cumulative_total=%d",
            prompt_tokens,
            completion_tokens,
            self._total_prompt_tokens + self._total_completion_tokens,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Generate text from a single prompt string.

        Args:
            prompt: The input text / instruction.
            max_tokens: Max tokens to generate (defaults to default_max_tokens).

        Returns:
            The generated text.

        Raises:
            RuntimeError: If all providers fail.
            ValueError: If prompt is empty.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty")

        effective_max_tokens = max_tokens or self.default_max_tokens
        logger.info(
            "Generating response (max_tokens=%d, prompt_length=%d chars)",
            effective_max_tokens,
            len(prompt),
        )

        messages = [{"role": "user", "content": prompt}]
        response = self._call_provider(messages, max_tokens=effective_max_tokens)

        self._track_usage(response["prompt_tokens"], response["completion_tokens"])
        return response["content"]

    def generate_messages(
        self,
        messages: list[dict[str, str]],
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text from a full message list (multi-turn / system messages).

        Args:
            messages: List of message dicts with "role" and "content" keys.
            max_tokens: Max tokens to generate.

        Returns:
            The generated text.

        Raises:
            RuntimeError: If all providers fail.
            ValueError: If messages list is empty.
        """
        if not messages:
            raise ValueError("Messages list must not be empty")

        effective_max_tokens = max_tokens or self.default_max_tokens
        response = self._call_provider(messages, max_tokens=effective_max_tokens)
        self._track_usage(response["prompt_tokens"], response["completion_tokens"])
        return response["content"]

    def summarize(self, text: str, max_length: Optional[int] = None) -> str:
        """Produce a concise summary of the provided text."""
        if not text or not text.strip():
            raise ValueError("Text to summarize must not be empty")

        token_budget = max_length or min(self.default_max_tokens, 512)

        prompt = (
            "You are a precise summarization assistant. Provide a clear, "
            "concise summary of the following text. Preserve key facts and "
            "main arguments. Do not add commentary.\n\n"
            f"TEXT:\n{text}\n\n"
            "SUMMARY:"
        )
        logger.info("Summarizing text (%d chars)", len(text))
        return self.generate(prompt, max_tokens=token_budget)

    def classify(self, text: str, labels: list[str]) -> str:
        """Classify text into one of the provided labels."""
        if not text or not text.strip():
            raise ValueError("Text to classify must not be empty")
        if not labels:
            raise ValueError("At least one label must be provided")

        labels_str = ", ".join(f'"{label}"' for label in labels)
        prompt = (
            "You are a text classification assistant. Classify the following "
            "text into exactly one of the given labels. Respond with ONLY the "
            "label, no explanation.\n\n"
            f"LABELS: {labels_str}\n\n"
            f"TEXT:\n{text}\n\n"
            "CLASSIFICATION:"
        )
        logger.info(
            "Classifying text (%d chars) into %d labels", len(text), len(labels)
        )

        result = self.generate(prompt, max_tokens=64).strip().strip('"')

        result_lower = result.lower()
        for label in labels:
            if label.lower() == result_lower:
                return label

        logger.warning(
            "Model returned '%s' which is not an exact label match; "
            "returning raw output",
            result,
        )
        return result

    def extract(self, text: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Extract structured data from text according to a provided schema."""
        if not text or not text.strip():
            raise ValueError("Text to extract from must not be empty")
        if not schema:
            raise ValueError("Schema must not be empty")

        import json

        schema_str = json.dumps(schema, indent=2)
        prompt = (
            "You are a structured data extraction assistant. Extract "
            "information from the following text according to the provided "
            "schema. Return ONLY valid JSON matching the schema. Use null "
            "for any fields that cannot be determined from the text.\n\n"
            f"SCHEMA:\n{schema_str}\n\n"
            f"TEXT:\n{text}\n\n"
            "EXTRACTED JSON:"
        )
        logger.info(
            "Extracting structured data (%d chars, %d fields)",
            len(text),
            len(schema),
        )

        raw = self.generate(prompt, max_tokens=self.default_max_tokens)

        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        try:
            extracted: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse extraction result as JSON: %s", exc)
            extracted = {key: None for key in schema}

        return extracted

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def get_usage_stats(self) -> dict[str, Any]:
        return {
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
            "total_requests": self._total_requests,
            "failed_requests": self._failed_requests,
            "fallback_requests": self._fallback_requests,
        }

    def reset_usage_stats(self) -> None:
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_requests = 0
        self._failed_requests = 0
        self._fallback_requests = 0
        logger.info("Usage statistics reset")
