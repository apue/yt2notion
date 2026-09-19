"""Offline contracts for shared execution observations and checkpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yt2notion.runtime import CheckpointStore, NodeExecutor, RuntimeObserver


def test_observations_preserve_nested_parentage_without_content(tmp_path: Path) -> None:
    observer = RuntimeObserver(tmp_path / "profile.json", run_name="subtitle_pack")

    with (
        observer.span("node", "generate") as node,
        observer.span("batch", "batch-0001", attributes={"item_count": 2}) as batch,
        observer.span(
            "provider_call",
            "translate",
            attributes={"input_chars": 20, "output_chars": 12},
        ) as call,
    ):
        pass
    observer.finish()

    payload = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in payload["observations"]}
    assert by_id[node.id]["parent_id"] == payload["run_id"]
    assert by_id[batch.id]["parent_id"] == node.id
    assert by_id[call.id]["parent_id"] == batch.id
    assert "content" not in json.dumps(payload)


def test_observer_rejects_content_bearing_attributes(tmp_path: Path) -> None:
    observer = RuntimeObserver(tmp_path / "profile.json", run_name="test")

    with pytest.raises(ValueError, match="content-bearing"):
        observer.record("provider_call", "call", attributes={"prompt": "secret"})


def test_interruption_is_persisted_without_error_message(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    observer = RuntimeObserver(path, run_name="test")
    error: BaseException | None = None

    with pytest.raises(KeyboardInterrupt):
        try:
            with observer.span("node", "interruptible"):
                raise KeyboardInterrupt("sensitive detail")
        except BaseException as exc:
            error = exc
            raise
        finally:
            observer.finish(error=error)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "interrupted"
    assert payload["error_type"] == "KeyboardInterrupt"
    assert payload["observations"][-1]["status"] == "interrupted"
    assert "sensitive detail" not in json.dumps(payload)


def test_checkpoint_identity_invalidates_and_records_reuse(tmp_path: Path) -> None:
    observer = RuntimeObserver(tmp_path / "profile.json", run_name="test")
    store = CheckpointStore(observer)
    checkpoint = tmp_path / "checkpoint.json"
    store.save(checkpoint, identity={"source": "a"}, result={"value": 1})

    assert store.load(checkpoint, identity={"source": "b"}) is None
    assert store.load(checkpoint, identity={"source": "a"}) == {"value": 1}
    observer.finish()

    payload = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    checkpoints = [item for item in payload["observations"] if item["kind"] == "checkpoint"]
    assert [item["attributes"]["outcome"] for item in checkpoints] == [
        "saved",
        "identity_mismatch",
        "reused",
    ]


def test_node_executor_runs_once_without_implicit_retry(tmp_path: Path) -> None:
    observer = RuntimeObserver(tmp_path / "profile.json", run_name="test")
    calls = 0

    def fail() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("failure")

    with pytest.raises(RuntimeError):
        NodeExecutor(observer).run("business_node", fail)

    assert calls == 1
