"""Bounded 20/100 diagnostics only; never substitutes for the frozen formal gate."""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
MULTI = ROOT / 'ci/multi_instance'
sys.path.insert(0, str(MULTI))
spec = importlib.util.spec_from_file_location('diagnostic_base', MULTI / 'run.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.PLAN = [20, 100]
original_child = base.child


def child(jobpath):
    import profiling
    original_metrics = profiling.Metrics
    class TransactionMetrics(original_metrics):
        def __init__(self, engine):
            super().__init__(engine)
            from go_hotel.api.routes import mobility
            from go_hotel.repositories.sql import repo
            from go_hotel.mobility.ride.service import ride_service
            from go_hotel.services.omnichannel_payment import omnichannel_payment_service
            for service, method, label in (
                (mobility, 'run_local_idempotent', 'route.run_local_idempotent'),
                (repo, 'complete_idempotency_in_session', 'idempotency.complete_in_session'),
                (ride_service, 'create_in_session', 'ride.create_in_session'),
                (omnichannel_payment_service, 'create_intent_in_session', 'payment.create_intent_in_session'),
            ):
                if hasattr(service, method):
                    self.track(service, method, label)
    profiling.Metrics = TransactionMetrics
    try:
        return original_child(jobpath)
    finally:
        profiling.Metrics = original_metrics


if __name__ == '__main__':
    base.child = child
    base.__file__ = __file__
    raise SystemExit(base.main())
