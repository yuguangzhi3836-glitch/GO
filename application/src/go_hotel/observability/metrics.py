from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
import time


class _Histogram:
    def __init__(self, capacity: int):
        self.samples = deque(maxlen=capacity)
        self.count = 0
        self.total = 0.0

    def observe(self, value: float):
        self.samples.append(value)
        self.count += 1
        self.total += value


class MetricsRegistry:
    """Process-local metrics with bounded samples per histogram label set.

    Counts and sums cover the process lifetime. P95 and histogram_values use
    the most recent samples, not an ever-growing history or a timed SLO window.
    Metric label cardinality must still be bounded by callers.
    """

    def __init__(self, max_histogram_samples: int = 4096):
        if not isinstance(max_histogram_samples, int) or max_histogram_samples < 1:
            raise ValueError('max_histogram_samples must be a positive integer')
        self._max_histogram_samples = max_histogram_samples
        self._lock = Lock()
        self._counters = defaultdict(float)
        self._hist = defaultdict(lambda: _Histogram(max_histogram_samples))
        self._gauges = {}

    @staticmethod
    def _key(name: str, labels: dict | None = None):
        return name, tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))

    def inc(self, name: str, value: float = 1, **labels):
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def observe(self, name: str, value: float, **labels):
        value = float(value)
        with self._lock:
            self._hist[self._key(name, labels)].observe(value)

    def set(self, name: str, value: float, **labels):
        with self._lock:
            self._gauges[self._key(name, labels)] = float(value)

    def snapshot(self):
        with self._lock:
            return {
                'counters': dict(self._counters),
                'histograms': {k: list(v.samples) for k, v in self._hist.items()},
                'histogram_totals': {k: (v.count, v.total) for k, v in self._hist.items()},
                'gauges': dict(self._gauges),
            }

    def counter_value(self, name: str, **labels):
        with self._lock:
            return self._counters.get(self._key(name, labels), 0.0)

    def histogram_values(self, name: str, **labels):
        with self._lock:
            histogram = self._hist.get(self._key(name, labels))
            return list(histogram.samples) if histogram is not None else []

    @staticmethod
    def _fmt_labels(labels):
        if not labels:
            return ''
        return '{' + ','.join(f'{k}="{v}"' for k, v in labels) + '}'

    def prometheus(self) -> str:
        snap = self.snapshot()
        lines = []
        for (name, labels), value in sorted(snap['counters'].items()):
            lines.append(f'{name}{self._fmt_labels(labels)} {value}')
        described = set()
        for key, values in sorted(snap['histograms'].items()):
            name, labels = key
            count, total = snap['histogram_totals'][key]
            label_text = self._fmt_labels(labels)
            lines.append(f'{name}_count{label_text} {count}')
            lines.append(f'{name}_sum{label_text} {total}')
            lines.append(f'{name}_retained_samples{label_text} {len(values)}')
            if values:
                if name not in described:
                    lines.append(f'# HELP {name}_p95 P95 of the most recent up to {self._max_histogram_samples} observations per label set.')
                    described.add(name)
                ordered = sorted(values)
                p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
                lines.append(f'{name}_p95{label_text} {p95}')
        for (name, labels), value in sorted(snap['gauges'].items()):
            lines.append(f'{name}{self._fmt_labels(labels)} {value}')
        return '\n'.join(lines) + '\n'


metrics = MetricsRegistry()


def now_monotonic():
    return time.perf_counter()
