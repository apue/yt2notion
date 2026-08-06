"""Small reusable stage-timing utility for application workflows."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class StageTimer:
    """Record elapsed wall-clock seconds for named workflow stages."""

    _started_at: float = field(default_factory=time.perf_counter)
    _durations: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        """Measure one stage, recording duration even when it raises."""
        started_at = time.perf_counter()
        try:
            yield
        finally:
            self._durations[stage] = time.perf_counter() - started_at

    def finish(self) -> dict[str, float]:
        """Return rounded stage durations plus total elapsed time."""
        timings = {name: round(value, 3) for name, value in self._durations.items()}
        timings["total"] = round(time.perf_counter() - self._started_at, 3)
        return timings
