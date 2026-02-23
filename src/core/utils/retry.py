"""
core.utils.retry
~~~~~~~~~~~~~~~~

Retry decorator with configurable exponential backoff for the OpenClaw system.

Provides a decorator and a context-manager for retrying operations that may
fail due to transient errors (network timeouts, rate limits, temporary
service unavailability).

Usage::

    from src.core.utils.retry import retry, RetryConfig

    # Decorator with defaults (3 retries, exponential backoff 1-60s)
    @retry()
    def fetch_offers():
        ...

    # Custom config
    @retry(max_retries=5, base_delay=2.0, catch=(ConnectionError, TimeoutError))
    def call_external_api():
        ...

    # As a context manager
    async with RetryConfig(max_retries=3).context():
        await http_client.get(url)
"""

from __future__ import annotations

import functools
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence, Type, TypeVar

from src.core.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_EXPONENTIAL_BASE,
    DEFAULT_RETRY_MAX_DELAY,
)

logger = logging.getLogger("openclaw.retry")

F = TypeVar("F", bound=Callable[..., Any])


# =====================================================================
# Configuration
# =====================================================================


@dataclass(frozen=True)
class RetryConfig:
    """Immutable configuration for retry behaviour.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts (0 = no retries, just the
        initial call).
    base_delay:
        Initial delay between retries in seconds.
    max_delay:
        Upper bound on the computed delay (caps exponential growth).
    exponential_base:
        Multiplier applied on each successive retry.
    jitter:
        If ``True``, add random jitter (0 to 50% of computed delay)
        to avoid thundering-herd problems.
    catch:
        Tuple of exception types that should trigger a retry.
        All other exceptions propagate immediately.
    on_retry:
        Optional callback invoked before each retry sleep.  Receives
        ``(attempt, exception, delay)`` as arguments.  Useful for
        logging or metrics.
    """

    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay: float = DEFAULT_RETRY_BASE_DELAY
    max_delay: float = DEFAULT_RETRY_MAX_DELAY
    exponential_base: float = DEFAULT_RETRY_EXPONENTIAL_BASE
    jitter: bool = True
    catch: tuple[Type[Exception], ...] = (Exception,)
    on_retry: Callable[[int, Exception, float], None] | None = None

    def compute_delay(self, attempt: int) -> float:
        """Compute the backoff delay for the given attempt number.

        Parameters
        ----------
        attempt:
            Zero-based attempt index (0 = first retry).

        Returns
        -------
        float
            Delay in seconds, clamped to :attr:`max_delay`, with
            optional jitter.
        """
        delay = self.base_delay * (self.exponential_base**attempt)
        delay = min(delay, self.max_delay)
        if self.jitter:
            delay += random.uniform(0, delay * 0.5)
        return delay


# =====================================================================
# Decorator
# =====================================================================


def retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    exponential_base: float = DEFAULT_RETRY_EXPONENTIAL_BASE,
    jitter: bool = True,
    catch: tuple[Type[Exception], ...] | Sequence[Type[Exception]] = (Exception,),
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> Callable[[F], F]:
    """Decorator that retries a function on transient failures.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts after the first call.
    base_delay:
        Initial delay (seconds) between retries.
    max_delay:
        Maximum delay (seconds) after exponential growth.
    exponential_base:
        Multiplier per retry attempt.
    jitter:
        Add random jitter to avoid thundering herd.
    catch:
        Exception types that trigger a retry.  Everything else
        propagates immediately.
    on_retry:
        Optional callback ``(attempt, exception, delay) -> None``
        invoked before each retry sleep.

    Returns
    -------
    Callable
        Decorated function.

    Examples
    --------
    >>> @retry(max_retries=2, base_delay=0.1, catch=(ValueError,))
    ... def flaky():
    ...     raise ValueError("oops")
    >>> flaky()  # Raises ValueError after 3 total attempts
    Traceback (most recent call last):
        ...
    ValueError: oops
    """
    catch_tuple = tuple(catch) if not isinstance(catch, tuple) else catch

    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        catch=catch_tuple,
        on_retry=on_retry,
    )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _execute_with_retry(func, args, kwargs, config)

        return wrapper  # type: ignore[return-value]

    return decorator


def _execute_with_retry(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    config: RetryConfig,
) -> Any:
    """Internal: execute *func* with retry logic.

    Parameters
    ----------
    func:
        The callable to execute.
    args:
        Positional arguments for *func*.
    kwargs:
        Keyword arguments for *func*.
    config:
        Retry configuration.

    Returns
    -------
    Any
        The return value of *func* on success.

    Raises
    ------
    Exception
        The last exception if all retries are exhausted.
    """
    last_exception: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except config.catch as exc:
            last_exception = exc
            if attempt >= config.max_retries:
                logger.error(
                    "All %d retries exhausted for %s: %s",
                    config.max_retries,
                    func.__qualname__,
                    exc,
                )
                raise

            delay = config.compute_delay(attempt)
            logger.warning(
                "Retry %d/%d for %s after %.2fs (error: %s)",
                attempt + 1,
                config.max_retries,
                func.__qualname__,
                delay,
                exc,
            )

            if config.on_retry is not None:
                config.on_retry(attempt, exc, delay)

            time.sleep(delay)

    # Should never reach here, but satisfy type checkers.
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")  # pragma: no cover


# =====================================================================
# Async decorator
# =====================================================================


def async_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    exponential_base: float = DEFAULT_RETRY_EXPONENTIAL_BASE,
    jitter: bool = True,
    catch: tuple[Type[Exception], ...] | Sequence[Type[Exception]] = (Exception,),
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> Callable[[F], F]:
    """Async version of :func:`retry` for coroutine functions.

    Parameters are identical to :func:`retry`.

    Examples
    --------
    >>> @async_retry(max_retries=2, catch=(ConnectionError,))
    ... async def fetch_data():
    ...     ...
    """
    import asyncio

    catch_tuple = tuple(catch) if not isinstance(catch, tuple) else catch

    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        catch=catch_tuple,
        on_retry=on_retry,
    )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except config.catch as exc:
                    last_exception = exc
                    if attempt >= config.max_retries:
                        logger.error(
                            "All %d async retries exhausted for %s: %s",
                            config.max_retries,
                            func.__qualname__,
                            exc,
                        )
                        raise

                    delay = config.compute_delay(attempt)
                    logger.warning(
                        "Async retry %d/%d for %s after %.2fs (error: %s)",
                        attempt + 1,
                        config.max_retries,
                        func.__qualname__,
                        delay,
                        exc,
                    )

                    if config.on_retry is not None:
                        config.on_retry(attempt, exc, delay)

                    await asyncio.sleep(delay)

            if last_exception is not None:
                raise last_exception
            raise RuntimeError("Unexpected async retry loop exit")

        return wrapper  # type: ignore[return-value]

    return decorator
