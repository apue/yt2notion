"""Retry helper with exponential backoff for transient failures."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryExhaustedError(Exception):
    """All retry attempts failed."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        super().__init__(f"Failed after {attempts} attempts: {last_error}")
        self.__cause__ = last_error


def retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 5.0,
    retryable: tuple[type[Exception], ...] = (Exception,),
    label: str = "",
) -> T:
    """Call fn(), retrying on retryable exceptions with exponential backoff.

    Args:
        fn: Zero-argument callable to invoke.
        max_retries: Maximum number of attempts.
        base_delay: Base delay in seconds (multiplied by 3^attempt).
        retryable: Tuple of exception types that trigger a retry.
        label: Label for log messages (e.g. "claude -p haiku").

    Returns:
        The return value of fn() on success.

    Raises:
        RetryExhaustedError: If all attempts fail with a retryable error.
        Exception: If fn() raises a non-retryable error (immediately).
    """
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except retryable as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (3 ** (attempt - 1))
                desc = label or "call"
                print(
                    f"Retry {attempt}/{max_retries} for {desc} "
                    f"(error: {e!s:.100}), waiting {delay:.0f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
    raise RetryExhaustedError(max_retries, last_error)  # type: ignore[arg-type]
