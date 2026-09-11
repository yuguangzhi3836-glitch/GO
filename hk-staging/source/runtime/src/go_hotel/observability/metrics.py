from __future__ import annotations
from collections import defaultdict
from threading import Lock
import time

class MetricsRegistry:
    """Small dependency-free Prometheus exposition registry for P0 runtime metrics."""
    def __init__(self):
        self._lock=Lock(); self._counters=defaultdict(float); self._hist=defaultdict(list); self._gauges={}
    @staticmethod
    def _key(name:str, labels:dict|None=None):
        labels=labels or {}
        return name, tuple(sorted((str(k),str(v)) for k,v in labels.items()))
    def inc(self,name:str,value:float=1,**labels):
        with self._lock: self._counters[self._key(name,labels)]+=value
    def observe(self,name:str,value:float,**labels):
        with self._lock: self._hist[self._key(name,labels)].append(float(value))
    def set(self,name:str,value:float,**labels):
        with self._lock: self._gauges[self._key(name,labels)]=float(value)
    def snapshot(self):
        with self._lock:
            return {"counters":dict(self._counters),"histograms":{k:list(v) for k,v in self._hist.items()},"gauges":dict(self._gauges)}
    def counter_value(self,name:str,**labels): return self.snapshot()["counters"].get(self._key(name,labels),0.0)
    def histogram_values(self,name:str,**labels): return self.snapshot()["histograms"].get(self._key(name,labels),[])
    @staticmethod
    def _fmt_labels(labels):
        if not labels:return ""
        return "{"+",".join(f'{k}="{v}"' for k,v in labels)+"}"
    def prometheus(self)->str:
        snap=self.snapshot(); lines=[]
        for (name,labels),value in sorted(snap['counters'].items()): lines.append(f"{name}{self._fmt_labels(labels)} {value}")
        for (name,labels),vals in sorted(snap['histograms'].items()):
            if vals:
                lines.append(f"{name}_count{self._fmt_labels(labels)} {len(vals)}")
                lines.append(f"{name}_sum{self._fmt_labels(labels)} {sum(vals)}")
                ordered=sorted(vals); p95=ordered[min(len(ordered)-1,int(len(ordered)*0.95))]
                lines.append(f"{name}_p95{self._fmt_labels(labels)} {p95}")
        for (name,labels),value in sorted(snap['gauges'].items()): lines.append(f"{name}{self._fmt_labels(labels)} {value}")
        return "\n".join(lines)+"\n"

metrics=MetricsRegistry()

def now_monotonic(): return time.perf_counter()
