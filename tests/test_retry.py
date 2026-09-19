"""Tests for retry helper."""

from __future__ import annotations

import json

import pytest

from yt2notion.retry import RetryExhaustedError, retry, retry_for_exceptions
from yt2notion.runtime import RuntimeObserver


def test_retry_succeeds_first_try():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry(fn, max_retries=3, base_delay=0.0, classify=retry_for_exceptions(Exception))
    assert result == "ok"
    assert len(calls) == 1


def test_retry_succeeds_after_failures():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    result = retry(
        fn,
        max_retries=3,
        base_delay=0.0,
        classify=retry_for_exceptions(ValueError),
    )
    assert result == "ok"
    assert len(calls) == 3


def test_retry_exhausted():
    def fn():
        raise ValueError("always fails")

    with pytest.raises(RetryExhaustedError) as exc_info:
        retry(
            fn,
            max_retries=3,
            base_delay=0.0,
            classify=retry_for_exceptions(ValueError),
        )
    assert exc_info.value.attempts == 3
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_retry_non_retryable_raises_immediately():
    calls = []

    def fn():
        calls.append(1)
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        retry(
            fn,
            max_retries=3,
            base_delay=0.0,
            classify=retry_for_exceptions(ValueError),
        )
    assert len(calls) == 1


def test_retry_logs_to_stderr(capsys):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("oops")
        return "ok"

    retry(
        fn,
        max_retries=3,
        base_delay=0.0,
        classify=retry_for_exceptions(ValueError),
        label="test-call",
    )
    captured = capsys.readouterr()
    assert "Retry 1/3" in captured.err
    assert "test-call" in captured.err


def test_retry_records_typed_attempts_under_provider_call(tmp_path):
    observer = RuntimeObserver(tmp_path / "profile.json", run_name="test")
    calls = 0

    def fn():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("secret provider response")
        return "ok"

    with observer.span("provider_call", "translate"):
        assert (
            retry(
                fn,
                max_retries=2,
                base_delay=0,
                classify=retry_for_exceptions(TimeoutError, category="transient"),
            )
            == "ok"
        )
    observer.finish()

    payload = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    attempts = [item for item in payload["observations"] if item["kind"] == "attempt"]
    assert [item["status"] for item in attempts] == ["failed", "completed"]
    assert attempts[0]["attributes"]["failure_category"] == "transient"
    assert "secret provider response" not in json.dumps(payload)
