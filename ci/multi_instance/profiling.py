"""Test-only diagnostics. No SQL parameters, URLs or application data recorded."""
from collections import defaultdict
from functools import wraps
import hashlib
import resource
import threading
import time
from sqlalchemy import event
from sqlalchemy.orm import Mapper

class Metrics:
    def __init__(self,engine):
        self.lock=threading.Lock();self.queries=defaultdict(lambda:[0,0.,0.])
        self.acquisitions=[];self.started=time.monotonic();self.cpu=resource.getrusage(resource.RUSAGE_SELF)
        self.holds=[];self.cache=defaultdict(int);self.mapper=[];self.mapper_started=None
        self.services=defaultdict(lambda:[0,0.,0.,0.])
        self.queue_waits=[]
        # Test-only observation of the recorded SQLAlchemy QueuePool's blocking
        # queue get. Unlike pool.connect timing, this excludes creation/pre-ping.
        queue_get=engine.pool._pool.get
        def measured_queue_get(block=True,timeout=None):
            start=time.monotonic()
            try:return queue_get(block,timeout)
            finally:
                if block:
                    with self.lock:self.queue_waits.append(time.monotonic()-start)
        engine.pool._pool.get=measured_queue_get
        @event.listens_for(Mapper,'before_configured')
        def mapper_before():
            self.mapper_started=(time.monotonic(),time.thread_time(),threading.get_ident())
        @event.listens_for(Mapper,'after_configured')
        def mapper_after():
            if self.mapper_started:
                wall,cpu,tid=self.mapper_started
                with self.lock:self.mapper.append({'wall_seconds':time.monotonic()-wall,
                    'configuring_thread_cpu_seconds':time.thread_time()-cpu if tid==threading.get_ident() else None})
                self.mapper_started=None
        @event.listens_for(engine.pool,'checkout')
        def checkout(dbapi_connection,connection_record,connection_proxy):
            connection_record.info['_mi_checkout_at']=time.monotonic()
        @event.listens_for(engine.pool,'checkin')
        def checkin(dbapi_connection,connection_record):
            start=connection_record.info.pop('_mi_checkout_at',None)
            if start is not None:
                with self.lock:self.holds.append(time.monotonic()-start)
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
                self.cache[getattr(context.cache_hit,'name',str(context.cache_hit))]+=1
    def track(self,service,method,label):
        original=getattr(service,method)
        @wraps(original)
        def measured(*args,**kwargs):
            wall=time.monotonic();cpu=time.thread_time()
            try:return original(*args,**kwargs)
            finally:
                elapsed=time.monotonic()-wall;used=time.thread_time()-cpu
                with self.lock:
                    row=self.services[label];row[0]+=1;row[1]+=elapsed;row[2]+=used;row[3]=max(row[3],elapsed)
        setattr(service,method,measured)
    def snapshot(self):
        usage=resource.getrusage(resource.RUSAGE_SELF)
        return {'wall_seconds':time.monotonic()-self.started,
            'user_cpu_seconds':usage.ru_utime-self.cpu.ru_utime,'system_cpu_seconds':usage.ru_stime-self.cpu.ru_stime,
            'peak_rss_kib':usage.ru_maxrss,'connection_acquisitions':len(self.acquisitions),
            'connection_acquisition_sum_seconds':sum(self.acquisitions),
            'connection_acquisition_max_seconds':max(self.acquisitions,default=0),
            'blocking_pool_queue_gets':len(self.queue_waits),
            'blocking_pool_queue_sum_seconds':sum(self.queue_waits),
            'blocking_pool_queue_max_seconds':max(self.queue_waits,default=0),
            'connection_holds':len(self.holds),'connection_hold_sum_seconds':sum(self.holds),
            'connection_hold_max_seconds':max(self.holds,default=0),
            'mapper_configuration':self.mapper,'statement_cache':dict(self.cache),
            'service_calls':{k:{'calls':v[0],'inclusive_wall_seconds':v[1],
                'inclusive_calling_thread_cpu_seconds':v[2],'max_wall_seconds':v[3]} for k,v in self.services.items()},
            'sql_count':sum(v[0] for v in self.queries.values()),
            'sql_sum_seconds':sum(v[1] for v in self.queries.values()),
            'sql':sorted([{'statement':k,'count':v[0],'sum_seconds':v[1],'max_seconds':v[2]} for k,v in self.queries.items()],key=lambda x:x['sum_seconds'],reverse=True),
            'note':'Summed concurrent wall times are not additive CPU time. Acquisition includes queueing, connection creation and pre-ping. SQL counts cover successful cursor events, excluding DBAPI ping/commit/rollback. SQL time includes transport, database execution and scheduling, but not statement compilation.'}
