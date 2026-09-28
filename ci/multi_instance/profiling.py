"""Test-only diagnostics. No SQL parameters, URLs or application data recorded."""
from collections import defaultdict
import hashlib
import resource
import threading
import time
from sqlalchemy import event

class Metrics:
    def __init__(self,engine):
        self.lock=threading.Lock();self.queries=defaultdict(lambda:[0,0.,0.])
        self.acquisitions=[];self.started=time.monotonic();self.cpu=resource.getrusage(resource.RUSAGE_SELF)
        original=engine.pool.connect
        def connect(*a,**kw):
            start=time.monotonic()
            try:return original(*a,**kw)
            finally:
                with self.lock:self.acquisitions.append(time.monotonic()-start)
        engine.pool.connect=connect
        @event.listens_for(engine,'before_cursor_execute')
        def before(conn,cursor,statement,parameters,context,executemany):
            context._mi_started=time.monotonic()
        @event.listens_for(engine,'after_cursor_execute')
        def after(conn,cursor,statement,parameters,context,executemany):
            elapsed=time.monotonic()-context._mi_started
            # Compiled SQL contains bind placeholders; retain only its hash and
            # operation so even literal-bearing statements cannot leak values.
            key=statement.split()[0]+' '+hashlib.sha256(statement.encode()).hexdigest()[:16]
            with self.lock:
                row=self.queries[key];row[0]+=1;row[1]+=elapsed;row[2]=max(row[2],elapsed)
    def snapshot(self):
        usage=resource.getrusage(resource.RUSAGE_SELF)
        return {'wall_seconds':time.monotonic()-self.started,
            'user_cpu_seconds':usage.ru_utime-self.cpu.ru_utime,'system_cpu_seconds':usage.ru_stime-self.cpu.ru_stime,
            'peak_rss_kib':usage.ru_maxrss,'connection_acquisitions':len(self.acquisitions),
            'connection_acquisition_sum_seconds':sum(self.acquisitions),
            'connection_acquisition_max_seconds':max(self.acquisitions,default=0),
            'sql_count':sum(v[0] for v in self.queries.values()),
            'sql_sum_seconds':sum(v[1] for v in self.queries.values()),
            'sql':sorted([{'statement':k,'count':v[0],'sum_seconds':v[1],'max_seconds':v[2]} for k,v in self.queries.items()],key=lambda x:x['sum_seconds'],reverse=True),
            'note':'Summed concurrent wall times are not additive CPU time. Acquisition includes queueing, connection creation and pre-ping. SQL time includes transport, database execution and scheduling.'}
