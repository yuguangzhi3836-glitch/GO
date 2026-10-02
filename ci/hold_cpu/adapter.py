"""Explicit opt-in adapter for the existing isolated multi_instance Metrics."""
from observe import HoldCPU


def with_hold_cpu(metrics_class):
    class LeaseMetrics(metrics_class):
        def __init__(self, engine):
            super().__init__(engine)
            self.hold_cpu = HoldCPU(engine)
            self.hold_cpu.wrap_transactions()
            self.hold_tracked = set()

        def track(self, service, method, label):
            super().track(service, method, label)
            identity = (id(service), method)
            if identity not in self.hold_tracked:
                self.hold_tracked.add(identity)
                self.hold_cpu.wrap(service, method, label)

        def snapshot(self):
            try:
                result = super().snapshot()
                result['held_cpu'] = self.hold_cpu.snapshot()
                if not result['held_cpu']['valid']:
                    raise RuntimeError('INVALID_HELD_CPU_DIAGNOSTIC')
                return result
            finally:
                self.hold_cpu.close()
    return LeaseMetrics
