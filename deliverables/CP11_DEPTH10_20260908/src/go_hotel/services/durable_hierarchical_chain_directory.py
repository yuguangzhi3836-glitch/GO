"""PostgreSQL-durable hierarchical directory adapter with emission outbox.

Discovery checkpoints immediately because they emit no business work. EMIT pages are
PREPARED in the durable outbox and do not advance the directory snapshot yet. The
caller enqueues deterministic task ids, then calls commit_emission(). A crash at any
point replays the same prepared batch; no hotel is skipped and task enqueue is
idempotent.
"""
from __future__ import annotations
import base64,json
from .chain_directory_snapshot_store import postgres_directory_snapshot_store
from .chain_directory_emission_outbox import chain_directory_emission_outbox
from .hierarchical_chain_directory import _new_state
from .chain_hotel_registry import OfficialPropertySeed,ChainCode
CURSOR_VERSION=1

def _encode_cursor(*,chain,snapshot_id,revision):
 raw=json.dumps({"v":CURSOR_VERSION,"chain":chain,"snapshot_id":snapshot_id,"revision":int(revision)},sort_keys=True,separators=(",",":")).encode();return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
def _decode_cursor(cursor):
 try:raw=base64.urlsafe_b64decode(cursor.encode("ascii")+b"="*(-len(cursor)%4));value=json.loads(raw.decode())
 except Exception as exc:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_INVALID") from exc
 if set(value)!={"v","chain","snapshot_id","revision"} or value["v"]!=CURSOR_VERSION or not isinstance(value["revision"],int) or value["revision"]<1 or not str(value["snapshot_id"]).startswith("dirsnap_"):raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_INVALID")
 return value

def _seed(row):
 return OfficialPropertySeed(chain=ChainCode(row["chain"]),official_property_id=row["official_property_id"],name=row["name"],property_url=row["property_url"],directory_url=row["directory_url"],country_code=row.get("country_code"),city=row.get("city"))

class DurableHierarchicalDirectoryAdapter:
 def __init__(self,adapter):self.adapter=adapter;self.chain=adapter.chain
 def _view(self,cursor,actor):
  chain=self.chain.value
  if cursor is None:return postgres_directory_snapshot_store.create(chain=chain,initial_state=_new_state(self.adapter.root_url),actor=actor)
  token=_decode_cursor(cursor)
  if token["chain"]!=chain:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_CHAIN_MISMATCH")
  view=postgres_directory_snapshot_store.load(snapshot_id=token["snapshot_id"],expected_chain=chain)
  if view.revision!=token["revision"]:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_STALE")
  return view
 def enumerate_page(self,fetch_page,cursor=None,*,actor="SYSTEM"):
  view=self._view(cursor,actor);chain=self.chain.value
  pending=chain_directory_emission_outbox.load_prepared(snapshot_id=view.snapshot_id,base_revision=view.revision)
  if pending and not pending.get("committed"):
   return [_seed(x) for x in pending["seeds"]],_encode_cursor(chain=chain,snapshot_id=view.snapshot_id,revision=view.revision),{"snapshot_id":view.snapshot_id,"revision":view.revision,"phase":"EMIT","inventory_sha256":pending["next_state"].get("inventory_sha256"),"property_count":len(pending["next_state"].get("frozen_inventory") or []),"emitted":pending["next_state"].get("emitted",0),"directory_complete":False,"emission_prepared":True,"batch_sha256":pending["batch_sha256"],"complete_after_commit":pending["complete"]}
  seeds,next_state,complete=self.adapter.enumerate_state(fetch_page,view.state)
  if seeds:
   prepared=chain_directory_emission_outbox.prepare(snapshot_id=view.snapshot_id,chain=chain,base_revision=view.revision,seeds=seeds,next_state=next_state,complete=complete,actor=actor)
   return seeds,_encode_cursor(chain=chain,snapshot_id=view.snapshot_id,revision=view.revision),{"snapshot_id":view.snapshot_id,"revision":view.revision,"phase":"EMIT","inventory_sha256":next_state.get("inventory_sha256"),"property_count":len(next_state.get("frozen_inventory") or []),"emitted":next_state.get("emitted",0),"directory_complete":False,"emission_prepared":True,"batch_sha256":prepared["batch_sha256"],"complete_after_commit":bool(complete)}
  saved=postgres_directory_snapshot_store.checkpoint(snapshot_id=view.snapshot_id,expected_revision=view.revision,state=next_state,actor=actor)
  return [],_encode_cursor(chain=chain,snapshot_id=saved.snapshot_id,revision=saved.revision),{"snapshot_id":saved.snapshot_id,"revision":saved.revision,"state_sha256":saved.state_sha256,"phase":next_state["phase"],"inventory_sha256":next_state.get("inventory_sha256"),"property_count":len(next_state.get("frozen_inventory") or []),"emitted":next_state.get("emitted",0),"directory_complete":False,"emission_prepared":False}
 def commit_emission(self,*,cursor,actor="SYSTEM"):
  token=_decode_cursor(cursor)
  if token["chain"]!=self.chain.value:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_CHAIN_MISMATCH")
  view=postgres_directory_snapshot_store.load(snapshot_id=token["snapshot_id"],expected_chain=self.chain.value)
  if view.revision!=token["revision"]:raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_STALE")
  pending=chain_directory_emission_outbox.load_prepared(snapshot_id=view.snapshot_id,base_revision=view.revision)
  if not pending or pending.get("committed"):raise ValueError("CHAIN_DIRECTORY_EMISSION_PENDING_REQUIRED")
  saved=postgres_directory_snapshot_store.checkpoint(snapshot_id=view.snapshot_id,expected_revision=view.revision,state=pending["next_state"],actor=actor)
  chain_directory_emission_outbox.mark_committed(snapshot_id=view.snapshot_id,base_revision=view.revision,committed_revision=saved.revision,state_sha256=saved.state_sha256,actor=actor)
  complete=bool(pending["complete"])
  return None if complete else _encode_cursor(chain=self.chain.value,snapshot_id=saved.snapshot_id,revision=saved.revision),{"snapshot_id":saved.snapshot_id,"revision":saved.revision,"state_sha256":saved.state_sha256,"directory_complete":complete,"batch_sha256":pending["batch_sha256"]}
