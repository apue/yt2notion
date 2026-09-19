"""Identity-bound JSON checkpoint persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generic, TypeVar

from yt2notion.runtime.observer import RuntimeObserver, active_observer

T = TypeVar("T")


class CheckpointStore(Generic[T]):
    """Persist and restore identity-bound JSON checkpoints."""

    def __init__(self, observer: RuntimeObserver | None = None) -> None:
        self.observer = observer or active_observer()

    def load(self, path: Path, *, identity: dict[str, object]) -> T | None:
        """Load a checkpoint only when its complete identity matches."""
        payload = self.load_payload(path, identity=identity)
        return payload.get("result") if payload is not None else None

    def load_payload(
        self,
        path: Path,
        *,
        identity: dict[str, object],
    ) -> dict[str, object] | None:
        """Load a schema-specific payload only when its identity matches."""
        outcome = "missing"
        result: dict[str, object] | None = None
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                outcome = "invalid"
            else:
                if not isinstance(payload, dict):
                    outcome = "invalid"
                elif payload.get("identity") != identity:
                    outcome = "identity_mismatch"
                else:
                    outcome = "reused"
                    result = payload
        self._record(path, outcome)
        return result

    def save(self, path: Path, *, identity: dict[str, object], result: T) -> None:
        """Persist a result using the established identity/result envelope."""
        self.save_payload(path, {"identity": identity, "result": result})

    def save_payload(self, path: Path, payload: dict[str, object]) -> None:
        """Persist a schema-specific checkpoint payload containing an identity."""
        if not isinstance(payload.get("identity"), dict):
            raise ValueError("checkpoint payload must contain an identity mapping")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._record(path, "saved")

    def _record(self, path: Path, outcome: str) -> None:
        if self.observer is not None:
            self.observer.record(
                "checkpoint",
                path.name,
                attributes={"outcome": outcome},
            )
