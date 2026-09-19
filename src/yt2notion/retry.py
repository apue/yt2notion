"""Typed provider-operation retry with exponential backoff."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Literal, TypeVar

from yt2notion.runtime import Observation, active_observer

T = TypeVar("T")
RetryCategory = Literal["transient", "rate_limit"]
RetryClassifier = Callable[[Exception], RetryCategory | None]


class RetryExhaustedError(Exception):
    """All retry attempts failed."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        super().__init__(f"Failed after {attempts} attempts: {last_error}")
        self.__cause__ = last_error


def retry_for_exceptions(
    *error_types: type[Exception],
    category: RetryCategory = "transient",
) -> RetryClassifier:
    """Build an explicit failure-category classifier for provider exceptions."""

    def classify(error: Exception) -> RetryCategory | None:
        return category if isinstance(error, error_types) else None

    return classify


def retry(
    fn: Callable[[], T],
    *,
    classify: RetryClassifier,
    max_retries: int = 3,
    base_delay: float = 5.0,
    label: str = "",
) -> T:
    """Retry one provider operation only for explicitly categorized failures."""
    last_error: Exception | None = None
    observer = active_observer()
    for attempt in range(1, max_retries + 1):
        category: RetryCategory | None = None
        span = (
            observer.span("attempt", f"attempt-{attempt}", attributes={"attempt": attempt})
            if observer is not None
            else nullcontext(None)
        )
        try:
            with span as observation:
                try:
                    return fn()
                except Exception as error:
                    category = classify(error)
                    if isinstance(observation, Observation):
                        observation.attributes["failure_category"] = category or "non_retryable"
                    raise
        except Exception as error:
            if category is None:
                raise
            last_error = error
            if attempt < max_retries:
                delay = base_delay * (3 ** (attempt - 1))
                desc = label or "call"
                print(
                    f"Retry {attempt}/{max_retries} for {desc} "
                    f"(error: {error!s:.100}), waiting {delay:.0f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
    if last_error is None:
        raise AssertionError("retry loop completed without an attempt")
    raise RetryExhaustedError(max_retries, last_error)
