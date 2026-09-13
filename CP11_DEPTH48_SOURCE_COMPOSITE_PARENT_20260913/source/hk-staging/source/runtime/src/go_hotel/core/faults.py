from __future__ import annotations
from threading import Lock

class FaultInjector:
    """Test-only deterministic failpoints. Production code has zero active faults by default."""
    def __init__(self):
        self._counts: dict[str, int] = {}
        self._lock = Lock()

    def arm(self, name: str, count: int = 1) -> None:
        with self._lock:
            self._counts[name] = count

    def clear(self) -> None:
        with self._lock:
            self._counts.clear()

    def hit(self, name: str) -> None:
        with self._lock:
            remaining = self._counts.get(name, 0)
            if remaining <= 0:
                return
            self._counts[name] = remaining - 1
        raise RuntimeError(f"Injected fault: {name}")

faults = FaultInjector()
