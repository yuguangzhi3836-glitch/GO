"""Freeze browser-visible official hotel inventory payloads without partner APIs.

This module is intentionally transport-neutral: a browser/crawler captures public
HTML hydration or XHR/JSON/GraphQL responses that an ordinary official page uses.
Only responses whose final URL is on the chain's approved official hosts may enter.
A contract is promotable only when every property has an explicit durable official
ID, name and official property URL and the observed inventory is stable across
independent captures. Heuristic title/name IDs are forbidden.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json
from urllib.parse import urlsplit
from .chain_hotel_registry import ChainCode,POLICIES,_host_allowed

@dataclass(frozen=True)
class PublicRuntimeCapture:
    chain:ChainCode;final_url:str;content_type:str;body:str

@dataclass(frozen=True)
class FrozenRuntimeInventory:
    chain:ChainCode;source_url:str;payload_sha256:str;inventory_sha256:str;properties:tuple[dict,...]

def _json(body):
    try:return json.loads(body)
    except Exception as exc:raise ValueError("CHAIN_RUNTIME_PAYLOAD_NOT_JSON") from exc

def _walk(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from _walk(child)
    elif isinstance(value,list):
        for child in value:yield from _walk(child)

def _first(obj,keys):
    for key in keys:
        value=obj.get(key)
        if isinstance(value,(str,int)) and str(value).strip():return str(value).strip()
    return None

def extract_explicit_properties(capture:PublicRuntimeCapture)->FrozenRuntimeInventory:
    parsed=urlsplit(capture.final_url);policy=POLICIES[capture.chain]
    if parsed.scheme!="https" or not parsed.hostname or not _host_allowed(parsed.hostname,policy.official_hosts):raise ValueError("CHAIN_RUNTIME_SOURCE_NOT_OFFICIAL")
    if "json" not in capture.content_type.lower():raise ValueError("CHAIN_RUNTIME_CONTENT_TYPE_NOT_JSON")
    data=_json(capture.body);found={}
    for obj in _walk(data):
        pid=_first(obj,("hotelId","hotelID","hotel_id","propertyId","propertyID","property_id","hotelCode","hotel_code"))
        name=_first(obj,("hotelName","hotel_name","propertyName","property_name","name"))
        url=_first(obj,("hotelUrl","hotelURL","hotel_url","propertyUrl","propertyURL","property_url","url"))
        if not (pid and name and url):continue
        p=urlsplit(url)
        if p.scheme!="https" or not p.hostname or not _host_allowed(p.hostname,policy.official_hosts):continue
        pid=pid.upper();item={"property_id":pid,"name":" ".join(name.split()),"url":url}
        existing=found.get(pid)
        if existing and existing!=item:raise ValueError(f"CHAIN_RUNTIME_PROPERTY_ID_CONFLICT:{capture.chain.value}:{pid}")
        found[pid]=item
    if not found:raise ValueError(f"CHAIN_RUNTIME_EXPLICIT_PROPERTY_INVENTORY_NOT_FOUND:{capture.chain.value}")
    ordered=tuple(found[k] for k in sorted(found))
    inventory_sha=hashlib.sha256(json.dumps(ordered,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    payload_sha=hashlib.sha256(capture.body.encode()).hexdigest()
    return FrozenRuntimeInventory(capture.chain,capture.final_url,payload_sha,inventory_sha,ordered)

def prove_stable_complete_inventory(captures:list[PublicRuntimeCapture],*,minimum_independent_captures:int=2)->FrozenRuntimeInventory:
    if len(captures)<minimum_independent_captures:raise ValueError("CHAIN_RUNTIME_INDEPENDENT_CAPTURES_REQUIRED")
    frozen=[extract_explicit_properties(x) for x in captures]
    chains={x.chain for x in frozen};inventories={x.inventory_sha256 for x in frozen}
    if len(chains)!=1:raise ValueError("CHAIN_RUNTIME_CAPTURE_CHAIN_MISMATCH")
    if len(inventories)!=1:raise ValueError("CHAIN_RUNTIME_INVENTORY_DRIFT")
    # Payload bytes may differ due to timestamps/session fields; the normalized explicit
    # property inventory must remain identical. Completeness still requires a separate
    # pagination/termination proof from the crawler before source-contract promotion.
    return frozen[0]
