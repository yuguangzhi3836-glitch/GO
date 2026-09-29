"""Yappi thread CPU diagnostics; never used to accept throughput improvements."""
from pathlib import Path
import resource
import time
import yappi


class CpuProbe:
    def start(self):
        assert not yappi.is_running(), 'PROFILER_ALREADY_RUNNING'
        yappi.clear_stats()
        yappi.set_context_backend('native_thread')
        yappi.set_clock_type('cpu')
        self.before = resource.getrusage(resource.RUSAGE_SELF)
        self.wall = time.monotonic_ns()
        yappi.start(builtins=True, profile_threads=True)

    def stop(self, root):
        yappi.stop()
        after = resource.getrusage(resource.RUSAGE_SELF)
        wall = (time.monotonic_ns()-self.wall)/1e9
        def filename(name):
            if name.startswith(str(root)):
                return str(Path(name).relative_to(root))
            if '/site-packages/' in name:
                return 'site-packages/'+name.split('/site-packages/', 1)[1]
            return name
        def functions(stats):
            rows = []
            for f in stats:
                assert f.tsub >= 0 and f.ttot >= 0, 'NEGATIVE_FUNCTION_CPU'
                rows.append({'file': filename(f.module), 'line': f.lineno,
                    'function': f.name, 'calls': f.ncall, 'primitive_calls': f.nactualcall,
                    'self_cpu_seconds': f.tsub, 'inclusive_cpu_seconds': f.ttot})
            return sorted(rows, key=lambda r:r['self_cpu_seconds'], reverse=True)
        threads = []
        for thread in yappi.get_thread_stats():
            # In 1.7.6 the keyword wrapper ignores ctx_id=0 (truthiness check).
            # The supported compatibility dict preserves the main-thread filter.
            rows = functions(yappi.get_func_stats(filter={'ctx_id': thread.id}))
            assert all(r['inclusive_cpu_seconds'] <= thread.ttot+.005 for r in rows), 'INVALID_THREAD_CPU'
            threads.append({'context_id': thread.id, 'thread_id': thread.tid,
                'thread_cpu_seconds': thread.ttot, 'functions': rows})
        return {'clock': yappi.get_clock_type(), 'wall_seconds': wall,
            'process_cpu_seconds': after.ru_utime+after.ru_stime-self.before.ru_utime-self.before.ru_stime,
            'threads': threads, 'functions': functions(yappi.get_func_stats()),
            'note': 'Yappi 1.7.6 CPU clock, native-thread contexts, including money replay threads. '
                'Exclusive CPU sums exclude nested calls; inclusive columns overlap. '
                'Observation overhead is included; these times are not optimization acceptance. '
                'Scope starts after service imports and includes thread creation, barriers and result serialization.'}
