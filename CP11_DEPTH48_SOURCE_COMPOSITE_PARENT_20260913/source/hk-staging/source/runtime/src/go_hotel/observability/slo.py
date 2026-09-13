from __future__ import annotations
from dataclasses import dataclass, asdict
from go_hotel.observability.metrics import metrics

@dataclass(frozen=True)
class SLO:
    key:str; target:float; window:str; description:str

SLOS=[
    SLO("api_availability",0.999,"30d","HTTP non-5xx availability"),
    SLO("booking_success",0.995,"30d","Confirmed booking workflow success excluding supplier-declared no inventory"),
    SLO("payment_orchestration_success",0.999,"30d","Authorization/book/capture orchestration reaches a safe terminal state"),
    SLO("refund_execution_success",0.995,"30d","Eligible refunds reach COMPLETED without manual repair"),
    SLO("connector_search_success",0.990,"7d","Activated connector search success"),
]

def current_slo_status():
    total=metrics.counter_value("go_http_requests_total")
    errors=metrics.counter_value("go_http_requests_5xx_total")
    availability=(1-errors/total) if total else 1.0
    return [{**asdict(s),"current":availability if s.key=="api_availability" else None,"status":("PASS" if availability>=s.target else "BREACH") if s.key=="api_availability" else "INSUFFICIENT_WINDOW_DATA"} for s in SLOS]
