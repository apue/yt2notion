"""Content-free profiling for subtitle package runs."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class ProfileRecorder:
    """Record stages and logical provider calls without prompt or subtitle text."""

    def __init__(self, output_dir: Path, *, inherited_timings: dict[str, float]) -> None:
        self.started = time.perf_counter()
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = output_dir / "profiles" / f"{self.run_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stages: list[dict[str, object]] = [
            {"name": name, "elapsed_seconds": elapsed, "source": "transcribe_workflow"}
            for name, elapsed in inherited_timings.items()
            if name != "total"
        ]
        self.calls: list[dict[str, object]] = []
        self.status = "running"
        self.error: str | None = None

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Measure one local stage."""
        started = time.perf_counter()
        status = "completed"
        try:
            yield
        except BaseException:
            status = "failed"
            raise
        finally:
            self.stages.append(
                {
                    "name": name,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "status": status,
                }
            )

    def record_call(
        self,
        *,
        operation: str,
        batch_id: str,
        cue_start: str | None,
        cue_end: str | None,
        input_chars: int,
        output_chars: int,
        elapsed_seconds: float,
        reused_checkpoint: bool,
        status: str,
    ) -> None:
        """Record one logical LLM call or checkpoint lookup."""
        self.calls.append(
            {
                "operation": operation,
                "batch_id": batch_id,
                "cue_start": cue_start,
                "cue_end": cue_end,
                "input_chars": input_chars,
                "output_chars": output_chars,
                "elapsed_seconds": round(elapsed_seconds, 3),
                "reused_checkpoint": reused_checkpoint,
                "status": status,
            }
        )

    def finish(self, *, error: BaseException | None = None) -> Path:
        """Persist a successful or failed profile and return its path."""
        self.status = "failed" if error else "completed"
        self.error = type(error).__name__ if error else None
        payload = {
            "schema_version": 1,
            "run_id": self.run_id,
            "status": self.status,
            "error_type": self.error,
            "elapsed_seconds": round(time.perf_counter() - self.started, 3),
            "stages": self.stages,
            "llm_calls": self.calls,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path
