"""Evidence projection helpers for PostgreSQL-backed runtime."""
from __future__ import annotations

UPSERT_PROJECTION_SQL = """
INSERT INTO c_runtime_evidence_projection(
  projection_key,last_event_hash,last_event_id,event_count,updated_at
)
VALUES (%s,%s,%s,%s,now())
ON CONFLICT(projection_key) DO UPDATE SET
  last_event_hash=EXCLUDED.last_event_hash,
  last_event_id=EXCLUDED.last_event_id,
  event_count=EXCLUDED.event_count,
  updated_at=now();
"""

def project_chain(conn, *, projection_key: str, events: list[dict]):
    last_hash = events[-1]["event_hash"] if events else None
    last_id = events[-1]["evidence_id"] if events else None
    with conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_PROJECTION_SQL,(projection_key,last_hash,last_id,len(events)))
    return {"projection_key":projection_key,"last_event_hash":last_hash,"last_event_id":last_id,"event_count":len(events)}
