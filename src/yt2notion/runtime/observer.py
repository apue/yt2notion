"""Nested content-free runtime observations and active provider context."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias

ObservationKind = Literal[
    "node",
    "batch",
    "provider_call",
    "attempt",
    "checkpoint",
    "availability",
]
ObservationStatus = Literal["running", "completed", "failed", "interrupted"]
Scalar: TypeAlias = str | int | float | bool | None

_ACTIVE_OBSERVER: ContextVar[RuntimeObserver | None] = ContextVar(
    "yt2notion_runtime_observer", default=None
)
_ACTIVE_PARENT: ContextVar[str | None] = ContextVar("yt2notion_runtime_parent", default=None)
_CONTENT_KEY_FRAGMENTS = (
    "prompt",
    "content",
    "text",
    "transcript",
    "subtitle",
    "api_key",
    "credential",
    "request_body",
    "response_body",
)


@dataclass
class Observation:
    """One content-free runtime observation."""

    id: str
    parent_id: str
    kind: ObservationKind
    name: str
    status: ObservationStatus = "running"
    elapsed_seconds: float = 0.0
    attributes: dict[str, Scalar] = field(default_factory=dict)
    error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the stable observation contract."""
        attributes = _validate_attributes(self.attributes)
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "attributes": attributes,
            "error_type": self.error_type,
        }


class RuntimeObserver:
    """Record nested run activity without prompts, content, or error messages."""

    def __init__(
        self,
        path: Path,
        *,
        run_name: str,
    ) -> None:
        self.run_name = run_name
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = path if path.suffix == ".json" else path / "profiles" / f"{self.run_id}.json"
        self._started = time.perf_counter()
        self._sequence = 0
        self._observations: list[Observation] = []

    @contextmanager
    def run(self) -> Iterator[RuntimeObserver]:
        """Activate and finish one product run, including interruptions."""
        error: BaseException | None = None
        observer_token = _ACTIVE_OBSERVER.set(self)
        parent_token = _ACTIVE_PARENT.set(self.run_id)
        try:
            yield self
        except BaseException as exc:
            error = exc
            raise
        finally:
            _ACTIVE_PARENT.reset(parent_token)
            _ACTIVE_OBSERVER.reset(observer_token)
            self.finish(error=error)

    def relocate(self, workspace_dir: Path) -> None:
        """Move final profile output to a workspace once acquisition identifies it."""
        self.path = workspace_dir / "profiles" / f"{self.run_id}.json"

    def timing_summary(self, names: tuple[str, ...]) -> dict[str, float]:
        """Return existing CLI stage timings from completed node observations."""
        timings = {
            name: round(
                sum(
                    observation.elapsed_seconds
                    for observation in self._observations
                    if observation.kind == "node" and observation.name == name
                ),
                3,
            )
            for name in names
        }
        timings["total"] = round(time.perf_counter() - self._started, 3)
        return timings

    @contextmanager
    def span(
        self,
        kind: ObservationKind,
        name: str,
        *,
        attributes: dict[str, Scalar] | None = None,
    ) -> Iterator[Observation]:
        """Record a nested operation, including failures and interruptions."""
        observation = self._new_observation(kind, name, attributes)
        started = time.perf_counter()
        observer_token = _ACTIVE_OBSERVER.set(self)
        parent_token = _ACTIVE_PARENT.set(observation.id)
        try:
            yield observation
        except BaseException as exc:
            observation.status = _status_for_error(exc)
            observation.error_type = type(exc).__name__
            raise
        else:
            observation.status = "completed"
        finally:
            observation.elapsed_seconds = time.perf_counter() - started
            self._observations.append(observation)
            _ACTIVE_PARENT.reset(parent_token)
            _ACTIVE_OBSERVER.reset(observer_token)

    def record(
        self,
        kind: ObservationKind,
        name: str,
        *,
        status: ObservationStatus = "completed",
        attributes: dict[str, Scalar] | None = None,
        error: BaseException | None = None,
        elapsed_seconds: float = 0.0,
    ) -> Observation:
        """Record an instantaneous observation under the active parent."""
        observation = self._new_observation(kind, name, attributes)
        observation.status = _status_for_error(error) if error else status
        observation.error_type = type(error).__name__ if error else None
        observation.elapsed_seconds = elapsed_seconds
        self._observations.append(observation)
        return observation

    def availability(
        self,
        provider: str,
        *,
        available: bool,
        failure_category: str | None = None,
    ) -> None:
        """Record passively observed provider availability without probing it."""
        self.record(
            "availability",
            provider,
            status="completed" if available else "failed",
            attributes={"available": available, "failure_category": failure_category},
        )

    def finish(self, *, error: BaseException | None = None) -> Path:
        """Persist the versioned run profile."""
        payload = {
            "schema_version": 2,
            "run_id": self.run_id,
            "run_name": self.run_name,
            "status": _status_for_error(error) if error else "completed",
            "error_type": type(error).__name__ if error else None,
            "elapsed_seconds": round(time.perf_counter() - self._started, 3),
            "observations": [observation.to_dict() for observation in self._observations],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def _new_observation(
        self,
        kind: ObservationKind,
        name: str,
        attributes: dict[str, Scalar] | None,
    ) -> Observation:
        sanitized = _validate_attributes(attributes or {})
        self._sequence += 1
        parent = _ACTIVE_PARENT.get() if _ACTIVE_OBSERVER.get() is self else None
        return Observation(
            id=f"{self.run_id}-{self._sequence:05d}",
            parent_id=parent or self.run_id,
            kind=kind,
            name=name,
            attributes=sanitized,
        )


def active_observer() -> RuntimeObserver | None:
    """Return the observer scoped to the current provider operation, if any."""
    return _ACTIVE_OBSERVER.get()


@contextmanager
def provider_call(
    name: str,
    *,
    attributes: dict[str, Scalar] | None = None,
) -> Iterator[Observation | None]:
    """Observe one provider operation when called inside an active product run."""
    observer = active_observer()
    if observer is None:
        yield None
        return
    with observer.span("provider_call", name, attributes=attributes) as observation:
        yield observation


def _validate_attributes(attributes: dict[str, Scalar]) -> dict[str, Scalar]:
    for key, value in attributes.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _CONTENT_KEY_FRAGMENTS):
            raise ValueError(f"content-bearing runtime attribute is forbidden: {key}")
        if isinstance(value, str) and ("\n" in value or len(value) > 200):
            raise ValueError(f"runtime attribute must be a bounded scalar: {key}")
    return dict(attributes)


def _status_for_error(error: BaseException | None) -> ObservationStatus:
    if error is None:
        return "completed"
    return "failed" if isinstance(error, Exception) else "interrupted"
