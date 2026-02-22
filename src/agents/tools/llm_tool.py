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
            (e.g. "openai", "anthropic", "local").
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

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the LLM tool with provider configuration.

        Args:
            config: Dictionary containing provider settings, API keys, and
                generation defaults. See class docstring for supported keys.
        """
        self.config = config

        # Primary provider settings
        self.primary_provider: str = config.get("primary_provider", "openai")
        self.primary_model: str = config.get("primary_model", "gpt-4")
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
        """Lazily initialize and return the primary provider client.

        Returns:
            The initialized client for the primary LLM provider.

        Raises:
            ConnectionError: If the primary provider cannot be reached.
            ValueError: If the provider name is not recognized.
        """
        if self._primary_client is None:
            self._primary_client = self._init_client(
                provider=self.primary_provider,
                model=self.primary_model,
                api_key=self.primary_api_key,
                base_url=self.primary_base_url,
            )
        return self._primary_client

    def _get_fallback_client(self) -> Any:
        """Lazily initialize and return the fallback provider client.

        Returns:
            The initialized client for the fallback LLM provider, or None
            if no fallback is configured.

        Raises:
            ConnectionError: If the fallback provider cannot be reached.
            ValueError: If the provider name is not recognized.
        """
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
            provider: Provider name (e.g. "openai", "anthropic", "local").
            model: Model identifier string.
            api_key: Authentication key for the provider API.
            base_url: Optional custom base URL for the API.

        Returns:
            An initialized provider client object.

        Raises:
            ValueError: If the provider is not supported.
            ConnectionError: If the provider API cannot be reached.
        """
        logger.debug("Initializing %s client for model %s", provider, model)
        # TODO: Implement provider-specific client initialization
        # Example:
        #   if provider == "openai":
        #       import openai
        #       return openai.OpenAI(api_key=api_key, base_url=base_url)
        #   elif provider == "anthropic":
        #       import anthropic
        #       return anthropic.Anthropic(api_key=api_key)
        raise NotImplementedError(f"Provider '{provider}' client initialization not yet implemented")

    # ------------------------------------------------------------------
    # Internal request handling
    # ------------------------------------------------------------------

    def _call_provider(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: Optional[float] = None,
        provider_override: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send a request to an LLM provider and return the raw response.

        Handles retry logic and automatic fallback to the secondary provider
        when the primary is unavailable.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            max_tokens: Maximum number of tokens to generate.
            temperature: Sampling temperature override. Uses instance default
                if not supplied.
            provider_override: Force a specific provider ("primary" or "fallback").

        Returns:
            Dict with keys:
                - "content" (str): The generated text.
                - "prompt_tokens" (int): Tokens used by the prompt.
                - "completion_tokens" (int): Tokens used by the completion.
                - "provider" (str): Which provider handled the request.
                - "model" (str): Which model was used.

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
                    # TODO: Implement actual API call to primary provider
                    raise NotImplementedError("Primary provider call not yet implemented")
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
                # TODO: Implement actual API call to fallback provider
                raise NotImplementedError("Fallback provider call not yet implemented")
            except Exception as exc:
                last_error = exc
                logger.error("Fallback provider also failed: %s", exc)

        self._failed_requests += 1
        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}"
        )

    def _track_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage from a completed request.

        Args:
            prompt_tokens: Number of tokens consumed by the prompt.
            completion_tokens: Number of tokens generated in the completion.
        """
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
        """Generate text from a prompt using the configured LLM provider.

        This is the fundamental generation method. All other public methods
        delegate to this after constructing an appropriate prompt.

        Args:
            prompt: The input text / instruction to send to the model.
            max_tokens: Maximum tokens to generate. Falls back to
                ``default_max_tokens`` if not provided.

        Returns:
            The generated text string.

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

    def summarize(self, text: str, max_length: Optional[int] = None) -> str:
        """Produce a concise summary of the provided text.

        Args:
            text: The source text to summarize.
            max_length: Optional hint for the desired summary length in tokens.

        Returns:
            A summarized version of the input text.

        Raises:
            RuntimeError: If all providers fail.
            ValueError: If text is empty.
        """
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
        """Classify text into one of the provided labels.

        Args:
            text: The text to classify.
            labels: A list of candidate label strings. The model must choose
                exactly one.

        Returns:
            The selected label string (guaranteed to be one of ``labels``).

        Raises:
            RuntimeError: If all providers fail.
            ValueError: If text or labels are empty.
        """
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

        # Attempt to match the model output to the closest provided label
        result_lower = result.lower()
        for label in labels:
            if label.lower() == result_lower:
                return label

        # Fuzzy fallback: return the raw result if no exact match
        logger.warning(
            "Model returned '%s' which is not an exact label match; "
            "returning raw output",
            result,
        )
        return result

    def extract(self, text: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Extract structured data from text according to a provided schema.

        Args:
            text: The source text containing the information to extract.
            schema: A dictionary describing the desired output fields and
                their types / descriptions. Example::

                    {
                        "product_name": "string - the name of the product",
                        "price": "float - the price in USD",
                        "features": "list[str] - key product features",
                    }

        Returns:
            A dictionary matching the provided schema with values populated
            from the text. Missing values will be ``None``.

        Raises:
            RuntimeError: If all providers fail.
            ValueError: If text or schema are empty.
        """
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
            # Return schema keys with None values as a safe fallback
            extracted = {key: None for key in schema}

        return extracted

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def get_usage_stats(self) -> dict[str, Any]:
        """Return cumulative token usage and request statistics.

        Returns:
            Dict containing:
                - total_prompt_tokens (int)
                - total_completion_tokens (int)
                - total_tokens (int)
                - total_requests (int)
                - failed_requests (int)
                - fallback_requests (int)
        """
        return {
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
            "total_requests": self._total_requests,
            "failed_requests": self._failed_requests,
            "fallback_requests": self._fallback_requests,
        }

    def reset_usage_stats(self) -> None:
        """Reset all accumulated usage counters to zero."""
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_requests = 0
        self._failed_requests = 0
        self._fallback_requests = 0
        logger.info("Usage statistics reset")
