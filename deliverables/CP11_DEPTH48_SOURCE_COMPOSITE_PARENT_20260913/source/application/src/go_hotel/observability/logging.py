from __future__ import annotations
import json, logging, sys
from datetime import datetime, timezone

class JsonFormatter(logging.Formatter):
    def format(self, record):
        base={"ts":datetime.now(timezone.utc).isoformat(),"level":record.levelname,"logger":record.name,"message":record.getMessage()}
        for k in ("request_id","trace_id","span_id","actor_id","supplier_id","path","method","status_code","duration_ms","event_type"):
            v=getattr(record,k,None)
            if v is not None: base[k]=v
        if record.exc_info: base["exception"]=self.formatException(record.exc_info)
        return json.dumps(base,separators=(",",":"),ensure_ascii=False)

def configure_json_logging():
    root=logging.getLogger(); root.setLevel(logging.INFO)
    if not any(getattr(h,"_go_json",False) for h in root.handlers):
        h=logging.StreamHandler(sys.stdout); h.setFormatter(JsonFormatter()); h._go_json=True; root.handlers=[h]
