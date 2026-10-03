"""Opt-in fixed-baseline diagnostic; original workload and gates unchanged."""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
ENTRY = str(Path(__file__).resolve())
spec = importlib.util.spec_from_file_location('held_process_pool', ROOT/'ci/process_pool/run.py')
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)
# The unchanged launcher recursively invokes this wrapper for coordinator and
# workers. ROOT has already been resolved from the original harness location.
pp.__file__ = ENTRY
pp.base.__file__ = ENTRY

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        import profiling
        from adapter import with_hold_cpu
        original = profiling.Metrics
        profiling.Metrics = with_hold_cpu(original)
        try:
            pp.base.child(Path(sys.argv[2]))
        finally:
            profiling.Metrics = original
    else:
        raise SystemExit(pp.main())
