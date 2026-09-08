"""Durable wrapper for hierarchical official directory adapters.

External cursors are intentionally tiny: version + chain + snapshot id + revision.
All discovery/emission state remains in PostgreSQL. The wrapped adapter still owns
official-host validation, redirect aliases, snapshot drift checks and frozen inventory
semantics; this wrapper owns durable checkpoint/restart/concurrency semantics.
"""
from __future__ import annotations
import base64, json

from .chain_directory_snapshot_store import postgres_directory_snapshot_store
from .hierarchical_chain_directory import _new_state

CURSOR_VERSION = 1


def _encode_cursor(*, chain: str, snapshot_id: str, revision: int) -> str:
    raw=json.dumps({"v":CURSOR_VERSION,"chain":chain,"snapshot_id":snapshot_id,"revision":int(revision)},sort_keys=True,separators=(",",":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict:
    try:
        raw=base64.urlsafe_b64decode(cursor.encode("ascii")+b"="*(-len(cursor)%4));value=json.loads(raw.decode())
    except Exception as exc: raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_INVALID") from exc
    if set(value)!={"v","chain","snapshot_id","revision"} or value["v"]!=CURSOR_VERSION or not isinstance(value["revision"],int) or value["revision"]<1 or not str(value["snapshot_id"]).startswith("dirsnap_"):
        raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_INVALID")
    return value


class DurableHierarchicalDirectoryAdapter:
    def __init__(self, adapter):
        self.adapter=adapter
        self.chain=adapter.chain

    def enumerate_page(self, fetch_page, cursor=None, *, actor="SYSTEM"):
        chain=self.chain.value
        if cursor is None:
            view=postgres_directory_snapshot_store.create(chain=chain,initial_state=_new_state(self.adapter.root_url),actor=actor)
        else:
            token=_decode_cursor(cursor)
            if token["chain"]!=chain: raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_CHAIN_MISMATCH")
            view=postgres_directory_snapshot_store.load(snapshot_id=token["snapshot_id"],expected_chain=chain)
            if view.revision!=token["revision"]: raise ValueError("CHAIN_DIRECTORY_DURABLE_CURSOR_STALE")
        internal_cursor=None
        from .hierarchical_chain_directory import _encode
        internal_cursor=_encode(view.state)
        seeds,next_internal=self.adapter.enumerate_page(fetch_page,internal_cursor)
        if next_internal is None:
            final_state=dict(view.state)
            # Re-run state extraction from the adapter result is impossible once its internal cursor is terminal.
            # Terminality itself is durable evidence only after the preceding checkpoint reached EMIT and the final
            # emitted chunk exhausts frozen_inventory. Advance the persisted emitted offset deterministically here.
            if final_state.get("phase")!="EMIT" or not isinstance(final_state.get("frozen_inventory"),list):
                raise ValueError("CHAIN_DIRECTORY_DURABLE_TERMINAL_WITHOUT_FROZEN_STATE")
            final_state["emitted"]=len(final_state["frozen_inventory"])
            final=postgres_directory_snapshot_store.checkpoint(snapshot_id=view.snapshot_id,expected_revision=view.revision,state=final_state,actor=actor)
            return seeds,None,{"snapshot_id":final.snapshot_id,"revision":final.revision,"state_sha256":final.state_sha256,"directory_complete":True}
        from .hierarchical_chain_directory import _decode
        next_state=_decode(next_internal,self.adapter.root_url)
        saved=postgres_directory_snapshot_store.checkpoint(snapshot_id=view.snapshot_id,expected_revision=view.revision,state=next_state,actor=actor)
        return seeds,_encode_cursor(chain=chain,snapshot_id=saved.snapshot_id,revision=saved.revision),{"snapshot_id":saved.snapshot_id,"revision":saved.revision,"state_sha256":saved.state_sha256,"directory_complete":False}
