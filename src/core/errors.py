"""
core.errors
~~~~~~~~~~~

Centralized exception hierarchy for the OpenClaw system.

Every module raises one of these so callers can handle errors uniformly.
Each exception carries an optional ``details`` dict for structured logging
and an optional ``cause`` for exception chaining without losing context.

Hierarchy
---------
::

    OpenClawError (base)
    +-- ConfigError
    +-- PipelineError
    |   +-- PipelineStepError
    |   +-- PipelineTimeoutError
    +-- AgentError
    |   +-- AgentNotRegisteredError
    |   +-- AgentTimeoutError
    +-- IntegrationError
    |   +-- APIRateLimitError
    |   +-- APIAuthenticationError
    |   +-- CircuitBreakerOpenError
    +-- PublishingError
    |   +-- CMSConnectionError
    |   +-- ContentValidationError
    |   +-- DuplicateContentError
    +-- SecurityError
    |   +-- CredentialMissingError
    |   +-- CredentialExpiredError
    +-- OrchestratorError
    |   +-- KillSwitchActiveError
    |   +-- InvalidStateTransitionError
    +-- PolicyViolationError
    |   +-- ContentPolicyViolationError
    |   +-- PostingPolicyViolationError
    |   +-- RiskPolicyViolationError
    +-- SchedulerError
    +-- RoutingError
"""

from __future__ import annotations

from typing import Any


# =====================================================================
# Base exception
# =====================================================================

class OpenClawError(Exception):
    """Base exception for all OpenClaw errors.

    Parameters
    ----------
    message:
        Human-readable description of what went wrong.
    details:
        Optional dict of structured context (agent name, pipeline step,
        request URL, etc.) that gets attached to the exception for
        logging and telemetry.
    cause:
        Optional original exception that triggered this one.  Stored
        separately from Python's built-in ``__cause__`` so callers
        can inspect it without try/except gymnastics.
    """

    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details or {}
        self.cause = cause

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        msg = str(self)
        if self.details:
            return f"{cls}({msg!r}, details={self.details!r})"
        return f"{cls}({msg!r})"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the exception into a JSON-friendly dictionary.

        Useful for structured logging and API error responses.
        """
        return {
            "error_type": self.__class__.__name__,
            "message": str(self),
            "details": self.details,
            "cause": repr(self.cause) if self.cause else None,
        }


# =====================================================================
# Configuration errors
# =====================================================================

class ConfigError(OpenClawError):
    """Raised when configuration is missing, malformed, or invalid.

    Examples: missing required .env variable, invalid YAML syntax,
    unrecognized agent name in ``config/agents.yaml``.
    """


# =====================================================================
# Pipeline errors
# =====================================================================

class PipelineError(OpenClawError):
    """Raised when a pipeline fails during execution."""


class PipelineStepError(PipelineError):
    """Raised when an individual step within a pipeline fails.

    The ``details`` dict should include ``step_name`` and ``step_index``
    so the orchestrator knows exactly where execution broke.
    """

    def __init__(
        self,
        message: str = "",
        *,
        step_name: str = "",
        step_index: int = -1,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        merged = {**(details or {}), "step_name": step_name, "step_index": step_index}
        super().__init__(message, details=merged, cause=cause)
        self.step_name = step_name
        self.step_index = step_index


class PipelineTimeoutError(PipelineError):
    """Raised when a pipeline exceeds its configured timeout budget."""


# =====================================================================
# Agent errors
# =====================================================================

class AgentError(OpenClawError):
    """Raised when an agent encounters an unrecoverable failure."""


class AgentNotRegisteredError(AgentError):
    """Raised when an operation targets an agent that was never registered."""


class AgentTimeoutError(AgentError):
    """Raised when an agent's run cycle exceeds its time budget."""


# =====================================================================
# Integration errors
# =====================================================================

class IntegrationError(OpenClawError):
    """Raised when an external service integration fails.

    Covers affiliate network APIs, CMS connections, DNS providers,
    analytics services, and any other third-party dependency.
    """


class APIRateLimitError(IntegrationError):
    """Raised when an external API returns a rate-limit response (HTTP 429).

    The ``details`` dict should contain ``retry_after`` (seconds) when
    the upstream provides that information.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        merged = {**(details or {})}
        if retry_after is not None:
            merged["retry_after"] = retry_after
        super().__init__(message, details=merged, cause=cause)
        self.retry_after = retry_after


class APIAuthenticationError(IntegrationError):
    """Raised when API credentials are rejected (HTTP 401/403)."""


class CircuitBreakerOpenError(IntegrationError):
    """Raised when a circuit breaker is open and the call is short-circuited.

    Callers should back off and retry after the circuit half-opens.
    """


# =====================================================================
# Publishing errors
# =====================================================================

class PublishingError(OpenClawError):
    """Raised when content publishing fails."""


class CMSConnectionError(PublishingError):
    """Raised when a CMS (WordPress, headless, etc.) cannot be reached."""


class ContentValidationError(PublishingError):
    """Raised when content fails pre-publish validation checks.

    Examples: below minimum word count, missing FTC disclosure,
    broken internal links, failed SEO score threshold.
    """


class DuplicateContentError(PublishingError):
    """Raised when content is substantially duplicate of existing published work."""


# =====================================================================
# Security errors
# =====================================================================

class SecurityError(OpenClawError):
    """Raised for security-related failures: credentials, permissions, etc."""


class CredentialMissingError(SecurityError):
    """Raised when a required credential is not found in the vault or environment."""


class CredentialExpiredError(SecurityError):
    """Raised when a credential exists but has expired and needs rotation."""


# =====================================================================
# Orchestrator errors
# =====================================================================

class OrchestratorError(OpenClawError):
    """Raised when the orchestrator encounters an unrecoverable state."""


class KillSwitchActiveError(OrchestratorError):
    """Raised when an action is attempted while the kill switch is engaged."""


class InvalidStateTransitionError(OrchestratorError):
    """Raised when a state machine transition is not allowed.

    The ``details`` dict should include ``from_state`` and ``to_state``.
    """

    def __init__(
        self,
        message: str = "",
        *,
        from_state: str = "",
        to_state: str = "",
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        merged = {
            **(details or {}),
            "from_state": from_state,
            "to_state": to_state,
        }
        super().__init__(message, details=merged, cause=cause)
        self.from_state = from_state
        self.to_state = to_state


# =====================================================================
# Policy errors
# =====================================================================

class PolicyViolationError(OpenClawError):
    """Raised when an action violates an enforced policy."""


class ContentPolicyViolationError(PolicyViolationError):
    """Raised when content fails quality, FTC, or SEO policy checks."""


class PostingPolicyViolationError(PolicyViolationError):
    """Raised when a publishing action violates posting-frequency or anti-spam rules."""


class RiskPolicyViolationError(PolicyViolationError):
    """Raised when an action exceeds acceptable risk thresholds."""


# =====================================================================
# Scheduling errors
# =====================================================================

class SchedulerError(OpenClawError):
    """Raised for scheduling failures (bad cron expression, missing config, etc.)."""


# =====================================================================
# Routing errors
# =====================================================================

class RoutingError(OpenClawError):
    """Raised when a task cannot be routed to any agent or node."""
