"""Tests for retry helper."""

from __future__ import annotations

import pytest

from yt2notion.retry import RetryExhaustedError, retry


def test_retry_succeeds_first_try():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry(fn, max_retries=3, base_delay=0.0)
    assert result == "ok"
    assert len(calls) == 1


def test_retry_succeeds_after_failures():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    result = retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,))
    assert result == "ok"
    assert len(calls) == 3


def test_retry_exhausted():
    def fn():
        raise ValueError("always fails")

    with pytest.raises(RetryExhaustedError) as exc_info:
        retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,))
    assert exc_info.value.attempts == 3
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_retry_non_retryable_raises_immediately():
    calls = []

    def fn():
        calls.append(1)
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,))
    assert len(calls) == 1


def test_retry_logs_to_stderr(capsys):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("oops")
        return "ok"

    retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,), label="test-call")
    captured = capsys.readouterr()
    assert "Retry 1/3" in captured.err
    assert "test-call" in captured.err
