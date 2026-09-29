"""Reuse the frozen full transaction gate with an optional thread CPU probe.

No application files or formal harness files are changed. This wrapper uses the
existing bounded 20/100 experiment mode at the unchanged default 5ms interval.
Each process records boundary CPU/RSS without per-call instrumentation in control.
"""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
MULTI = ROOT / 'ci/multi_instance'
sys.path.insert(0, str(MULTI))
spec = importlib.util.spec_from_file_location('cpu_base', MULTI/'run.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
original_child = base.child


def child(jobpath):
    import json
    job = json.loads(jobpath.read_text())
    profile = None
    if jobpath.parent.name == 'profile' and all(t['op'] == 'ride' for t in job['tasks']):
        base.imports()
        import ride_workload
        from go_hotel.rail.service import rail_service
        from go_hotel.attractions.service import attraction_service
        from thread_profile import CpuProbe
        profile = CpuProbe()
        profile.start()
    try:
        original_child(jobpath)
    finally:
        if profile:
            base.write(Path(job['result']+'.thread-cpu.json'), profile.stop(ROOT))


if __name__ == '__main__':
    # All spawned coordinators/service children come through this wrapper. The
    # imported harness ROOT/APP remain the real repository paths.
    base.child = child
    base.__file__ = __file__
    raise SystemExit(base.main())
