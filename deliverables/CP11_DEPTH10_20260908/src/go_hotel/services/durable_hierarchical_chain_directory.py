"""PostgreSQL-durable wrapper for hierarchical official directory adapters.

External cursors contain only version, chain, snapshot id and revision. The complete
discovery/emission state is persisted in PostgreSQL after every call. Optimistic
revision checks plus the snapshot store advisory lock reject stale/concurrent cursors.
"""
from __future__ import annotations
import base64,json
from .chain_directory_snapshot_store import postgres_directory_snapshot_store
from .hierarchical_chain_directory import _new_state
CURSOR_VERSION=1
def _encode_cursor(*,chain,snapshot_id,revision):
 raw=json.dumps({"v":CURSOR_VERSION,"chain":chain,"snapshot_id":snapshot_id,"revision":int(revision)},sort_keys=True,separators=(",",":")).encode();return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
def _decode_cursor(cursor):
 try:raw=base64.urlsafe_b64decode(cursor.encode("ascii")+b"="*(-len(cursor)%4));value=json.loads(raw.decode())
 except Exception as exc:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_INVALID") from exc
 if set(value)!={"v","chain","snapshot_id","revision"} or value["v"]!=CURSOR_VERSION or not isinstance(value["revision"],int) or value["revision"]<1 or not str(value["snapshot_id"]).startswith("dirsnap_"):raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_INVALID")
 return value
class DurableHierarchicalDirectoryAdapter:
 def __init__(self,adapter):self.adapter=adapter;self.chain=adapter.chain
 def enumerate_page(self,fetch_page,cursor=None,*,actor="SYSTEM"):
  chain=self.chain.value
  if cursor is None:view=postgres_directory_snapshot_store.create(chain=chain,initial_state=_new_state(self.adapter.root_url),actor=actor)
  else:
   token=_decode_cursor(cursor)
   if token["chain"]!=chain:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_CHAIN_MISMATCH")
   view=postgres_directory_snapshot_store.load(snapshot_id=token["snapshot_id"],expected_chain=chain)
   if view.revision!=token["revision"]:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_STALE")
  seeds,next_state,complete=self.adapter.enumerate_state(fetch_page,view.state)
  saved=postgres_directory_snapshot_store.checkpoint(snapshot_id=view.snapshot_id,expected_revision=view.revision,state=next_state,actor=actor)
  evidence={"snapshot_id":saved.snapshot_id,"revision":saved.revision,"state_sha256":saved.state_sha256,"phase":next_state["phase"],"inventory_sha256":next_state.get("inventory_sha256"),"property_count":len(next_state.get("frozen_inventory") or []),"emitted":next_state.get("emitted",0),"directory_complete":bool(complete)}
  return seeds,(None if complete else _encode_cursor(chain=chain,snapshot_id=saved.snapshot_id,revision=saved.revision)),evidence
