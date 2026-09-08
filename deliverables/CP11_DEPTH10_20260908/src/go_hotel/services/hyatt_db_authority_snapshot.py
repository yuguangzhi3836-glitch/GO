"""Authoritative PostgreSQL snapshot for Hyatt generation idempotency checks.

Persisted entities and active/publication state must remain stable across reruns.
Append-only audit history is allowed to grow and is reported separately. New hotel
or room entities, media identity/state drift, or new active/page versions fail closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from sqlalchemy import inspect, select, text

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal
from .durable_media_index import durable_media_index_service

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HOTEL_TABLE_HINTS = ("hotels", "hotel", "hotel_entities", "hotel_master")
ROOM_TABLE_HINTS = ("hotel_room_types", "room_types", "hotel_rooms", "room_type")
PAGE_TOKENS = ("PAGE", "LKG", "PUBLISH", "GOLDEN", "AUTO_PAGE")


def _qid(name: str) -> str:
    if not _IDENT.fullmatch(name): raise RuntimeError("DB_AUTHORITY_IDENTIFIER_INVALID")
    return '"' + name + '"'

def _columns(inspector, table: str) -> set[str]: return {str(x["name"]) for x in inspector.get_columns(table)}
def _resolve_table(inspector, *, env_name: str, required: set[str], hints: tuple[str, ...]) -> str:
    configured=str(os.getenv(env_name) or "").strip()
    if configured:
        if configured not in inspector.get_table_names() or not required.issubset(_columns(inspector,configured)):raise RuntimeError(f"DB_AUTHORITY_CONFIGURED_TABLE_INVALID:{env_name}")
        return configured
    candidates=[]
    for table in inspector.get_table_names():
        cols=_columns(inspector,table)
        if required.issubset(cols):
            score=100 if table in hints else sum(10 for hint in hints if hint in table);candidates.append((score,table))
    if not candidates:raise RuntimeError(f"DB_AUTHORITY_TABLE_NOT_FOUND:{env_name}")
    candidates.sort(reverse=True)
    if len(candidates)>1 and candidates[0][0]==candidates[1][0]:raise RuntimeError(f"DB_AUTHORITY_TABLE_AMBIGUOUS:{env_name}:{candidates[0][1]}:{candidates[1][1]}")
    return candidates[0][1]
def _identity_column(cols:set[str],choices:tuple[str,...])->str:
    for name in choices:
        if name in cols:return name
    raise RuntimeError("DB_AUTHORITY_ID_COLUMN_NOT_FOUND")
def _rows_for_hotel(session,table,hotel_col,hotel_id,id_col):
    sql=text(f"SELECT {_qid(id_col)} FROM {_qid(table)} WHERE {_qid(hotel_col)}=:hotel_id ORDER BY {_qid(id_col)}");return [str(x[0]) for x in session.execute(sql,{"hotel_id":hotel_id}).all()]
def _hotel_identity(session,table,hotel_id,id_col):
    sql=text(f"SELECT {_qid(id_col)} FROM {_qid(table)} WHERE {_qid(id_col)}=:hotel_id ORDER BY {_qid(id_col)}");return [str(x[0]) for x in session.execute(sql,{"hotel_id":hotel_id}).all()]
def _page_state(hotel_id:str)->dict:
    with SessionLocal() as s:rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.hotel_id==hotel_id).order_by(HotelAutoPageEventRow.created_at.asc())).all()
    audit_ids=[];versions=set();active_versions=set();publication_states=[]
    for row in rows:
        et=str(row.event_type or "").upper()
        if not any(token in et for token in PAGE_TOKENS):continue
        ev=dict(row.evidence_json or {});audit_ids.append(str(row.hotel_auto_page_event_id))
        for key in ("page_version","version","candidate_version","previous_page_version","failed_candidate_version","active_page_version"):
            if ev.get(key):versions.add(str(ev[key]))
        if ev.get("active_page_version"):active_versions.add(str(ev["active_page_version"]))
        if ev.get("publication_state"):publication_states.append(str(ev["publication_state"]))
    return {"audit_event_count":len(audit_ids),"audit_event_ids":audit_ids,"page_versions":sorted(versions),"active_page_versions":sorted(active_versions),"publication_states":publication_states}
def snapshot(*,hotel_id:str)->dict:
    if not hotel_id:raise ValueError("HYATT_DB_SNAPSHOT_HOTEL_ID_REQUIRED")
    with SessionLocal() as s:
        if s.get_bind().dialect.name!="postgresql":raise RuntimeError("POSTGRES_REQUIRED")
        inspector=inspect(s.get_bind());hotel_table=_resolve_table(inspector,env_name="GO_HOTEL_ENTITY_TABLE",required={"hotel_id"},hints=HOTEL_TABLE_HINTS);room_table=_resolve_table(inspector,env_name="GO_ROOM_ENTITY_TABLE",required={"hotel_id"},hints=ROOM_TABLE_HINTS)
        hotel_cols=_columns(inspector,hotel_table);room_cols=_columns(inspector,room_table);hotel_id_col=_identity_column(hotel_cols,("hotel_id","id"));room_id_col=_identity_column(room_cols,("room_type_id","hotel_room_type_id","room_id","id"));hotel_ids=_hotel_identity(s,hotel_table,hotel_id,hotel_id_col);room_ids=_rows_for_hotel(s,room_table,"hotel_id",hotel_id,room_id_col)
    media=durable_media_index_service.list_assets(hotel_id=hotel_id);media_state=[{"asset_id":str(x.get("asset_id") or ""),"room_type_id":str(x.get("room_type_id") or ""),"sha256":str(x.get("sha256") or ""),"publication_state":str(x.get("publication_state") or ""),"rights_state":str(x.get("rights_state") or "")} for x in media];media_state.sort(key=lambda x:x["asset_id"])
    page=_page_state(hotel_id);core={"hotel_table":hotel_table,"room_table":room_table,"hotel_ids":hotel_ids,"room_ids":room_ids,"media_assets":media_state,"page_state":page};digest=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest();return {**core,"snapshot_sha256":digest}
def diff(base:dict,current:dict)->dict:
    bh,ch=set(base.get("hotel_ids") or []),set(current.get("hotel_ids") or []);br,cr=set(base.get("room_ids") or []),set(current.get("room_ids") or [])
    bm={x["asset_id"]:x for x in (base.get("media_assets") or [])};cm={x["asset_id"]:x for x in (current.get("media_assets") or [])}
    bp=set((base.get("page_state") or {}).get("page_versions") or []);cp=set((current.get("page_state") or {}).get("page_versions") or []);ba=set((base.get("page_state") or {}).get("active_page_versions") or []);ca=set((current.get("page_state") or {}).get("active_page_versions") or [])
    media_changed=sorted(k for k in bm.keys()&cm.keys() if bm[k]!=cm[k]);audit_before=int((base.get("page_state") or {}).get("audit_event_count") or 0);audit_after=int((current.get("page_state") or {}).get("audit_event_count") or 0)
    forbidden={"hotel_entity_added":sorted(ch-bh),"hotel_entity_removed":sorted(bh-ch),"room_entity_added":sorted(cr-br),"room_entity_removed":sorted(br-cr),"media_asset_added":sorted(cm.keys()-bm.keys()),"media_asset_removed":sorted(bm.keys()-cm.keys()),"media_asset_changed":media_changed,"page_version_added":sorted(cp-bp),"active_page_version_added":sorted(ca-ba)}
    forbidden_growth=any(bool(v) for v in forbidden.values())
    return {**forbidden,"hotel_entity_count":len(ch),"room_entity_count":len(cr),"media_asset_count":len(cm),"audit_event_count_before":audit_before,"audit_event_count_after":audit_after,"audit_event_growth":max(0,audit_after-audit_before),"audit_growth_allowed":audit_after>=audit_before,"forbidden_state_proliferation":forbidden_growth,"zero_proliferation":not forbidden_growth}
