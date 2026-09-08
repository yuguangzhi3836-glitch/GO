"""Resumable two-phase crawler for official hierarchical hotel directories.

Phase 1 DISCOVER follows only approved official-host links and emits no properties.
When the frontier is exhausted, the complete property set is frozen with a snapshot
SHA. Phase 2 EMIT pages only from that frozen ordered inventory. This prevents a
late-discovered property from sorting before an already-emitted offset and causing
skips/duplicates. Redirect aliases are canonicalized and persisted so resume is
idempotent across URL aliases.
"""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import json
from urllib.parse import urljoin, urlsplit, urlunsplit

from .chain_hotel_registry import ChainDirectoryAdapter, OfficialPropertySeed, POLICIES
from .chain_official_source_contracts import assert_directory_production_ready, validate_contract_document


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.current=None; self.text=[]; self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()!="a" or self.current is not None:return
        href=str(dict(attrs).get("href") or "").strip()
        if href:self.current=href;self.text=[]
    def handle_data(self,data):
        if self.current is not None:self.text.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=="a" and self.current is not None:
            self.links.append((self.current," ".join(" ".join(self.text).split())));self.current=None;self.text=[]


def _host_allowed(host,roots):
    host=str(host or "").lower().rstrip(".");return bool(host) and any(host==r or host.endswith("."+r) for r in roots)

def _canonical_absolute(url:str)->str|None:
    p=urlsplit(url)
    if p.scheme!="https" or not p.hostname or p.username or p.password:return None
    host=p.hostname.lower().rstrip(".");port=f":{p.port}" if p.port and p.port!=443 else ""
    path=p.path or "/"
    return urlunsplit(("https",host+port,path,p.query,""))

def _canonical_url(base,href):return _canonical_absolute(urljoin(base,href))

def _encode(state):
    raw=json.dumps(state,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode();return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _new_state(root):
    return {"phase":"DISCOVER","frontier":[root],"visited":[],"aliases":{},"properties":{},"page_digests":{},"frozen_inventory":None,"inventory_sha256":None,"emitted":0}

def _decode(cursor,root):
    if not cursor:return _new_state(root)
    try:raw=base64.urlsafe_b64decode(cursor.encode("ascii")+b"="*(-len(cursor)%4));state=json.loads(raw.decode("utf-8"))
    except Exception as exc:raise ValueError("CHAIN_HIERARCHY_CURSOR_INVALID") from exc
    required={"phase","frontier","visited","aliases","properties","page_digests","frozen_inventory","inventory_sha256","emitted"}
    if set(state)!=required or state["phase"] not in {"DISCOVER","EMIT"} or not isinstance(state["frontier"],list) or not isinstance(state["visited"],list) or not isinstance(state["aliases"],dict) or not isinstance(state["properties"],dict) or not isinstance(state["page_digests"],dict) or not isinstance(state["emitted"],int) or state["emitted"]<0:raise ValueError("CHAIN_HIERARCHY_CURSOR_INVALID")
    if state["phase"]=="EMIT":
        if not isinstance(state["frozen_inventory"],list) or not state["inventory_sha256"] or state["frontier"]:raise ValueError("CHAIN_HIERARCHY_CURSOR_INVALID")
        expected=hashlib.sha256(json.dumps(state["frozen_inventory"],sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        if expected!=state["inventory_sha256"]:raise ValueError("CHAIN_HIERARCHY_FROZEN_INVENTORY_TAMPERED")
    return state


class HierarchicalOfficialDirectoryAdapter(ChainDirectoryAdapter):
    max_pages_per_call=8;max_total_pages=2000;page_size=50
    def __init__(self,*,page_size=50,max_pages_per_call=8):
        contract=assert_directory_production_ready(self.chain)
        if not 1<=int(page_size)<=100:raise ValueError("CHAIN_DIRECTORY_PAGE_SIZE_INVALID")
        if not 1<=int(max_pages_per_call)<=50:raise ValueError("CHAIN_DIRECTORY_PAGE_BUDGET_INVALID")
        self.root_url=_canonical_absolute(contract.directory_url) or contract.directory_url;self.page_size=int(page_size);self.max_pages_per_call=int(max_pages_per_call)
    def classify_official_link(self,url,label):raise NotImplementedError
    def _fetch(self,fetch_page,url):
        value=fetch_page(url)
        if isinstance(value,str):return url,value
        if isinstance(value,tuple) and len(value)>=2:return str(value[0]),str(value[1])
        raise ValueError("CHAIN_DIRECTORY_FETCH_RESULT_INVALID")
    def _freeze(self,state):
        if state["frontier"]:raise ValueError("CHAIN_DIRECTORY_FREEZE_WITH_PENDING_FRONTIER")
        ordered=[{"property_id":pid,"name":item["name"],"url":item["url"]} for pid,item in sorted(state["properties"].items())]
        if not ordered:raise ValueError(f"CHAIN_DIRECTORY_NO_PROPERTIES_FOUND:{self.chain.value}")
        state["frozen_inventory"]=ordered;state["inventory_sha256"]=hashlib.sha256(json.dumps(ordered,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest();state["phase"]="EMIT";state["emitted"]=0
    def _discover(self,fetch_page,state,policy):
        pages=0
        visited=set(state["visited"])
        while state["frontier"] and pages<self.max_pages_per_call:
            requested=state["frontier"].pop(0);requested_c=_canonical_absolute(requested)
            if not requested_c:raise ValueError("CHAIN_DIRECTORY_REQUEST_URL_INVALID")
            alias_target=state["aliases"].get(requested_c)
            if alias_target in visited:continue
            if requested_c in visited:continue
            final_raw,html=self._fetch(fetch_page,requested_c);final=_canonical_absolute(final_raw)
            if not final:raise ValueError("CHAIN_DIRECTORY_FINAL_URL_INVALID")
            p=urlsplit(final)
            if not _host_allowed(p.hostname,policy.official_hosts):raise ValueError("CHAIN_DIRECTORY_FINAL_URL_NOT_OFFICIAL")
            state["aliases"][requested_c]=final
            if final in visited:continue
            if not state["visited"]:validate_contract_document(self.chain,final_url=final,text=html)
            digest=hashlib.sha256(html.encode()).hexdigest();previous=state["page_digests"].get(final)
            if previous and previous!=digest:raise ValueError(f"CHAIN_DIRECTORY_SNAPSHOT_CHANGED:{self.chain.value}")
            state["page_digests"][final]=digest;parser=LinkParser();parser.feed(html)
            for href,label in parser.links:
                absolute=_canonical_url(final,href)
                if not absolute:continue
                ap=urlsplit(absolute)
                if not _host_allowed(ap.hostname,policy.official_hosts):continue
                classified=self.classify_official_link(absolute,label)
                if not classified:continue
                kind,data=classified
                if kind=="DIRECTORY":
                    known=state["aliases"].get(absolute,absolute)
                    if known not in visited and absolute not in state["frontier"]:state["frontier"].append(absolute)
                elif kind=="PROPERTY":
                    property_id,name=data;property_id=str(property_id).strip().upper();name=" ".join(str(name or "").split())
                    if not property_id or len(name)<3:continue
                    existing=state["properties"].get(property_id)
                    if existing and (existing["name"].casefold()!=name.casefold() or existing["url"]!=absolute):raise ValueError(f"CHAIN_DIRECTORY_PROPERTY_ID_CONFLICT:{self.chain.value}:{property_id}")
                    state["properties"][property_id]={"name":name,"url":absolute}
            state["visited"].append(final);visited.add(final);pages+=1
            if len(visited)+len(state["frontier"])>self.max_total_pages:raise ValueError("CHAIN_DIRECTORY_TOTAL_PAGE_BUDGET_EXHAUSTED")
        if not state["frontier"]:self._freeze(state)
    def _emit(self,state):
        frozen=state["frozen_inventory"] or [];start=state["emitted"];chunk=frozen[start:start+self.page_size]
        seeds=[OfficialPropertySeed(chain=self.chain,official_property_id=item["property_id"],name=item["name"],property_url=item["url"],directory_url=self.root_url,country_code=getattr(self,"country_code",None)) for item in chunk]
        seeds=self.validate(seeds);state["emitted"]=start+len(chunk)
        if state["emitted"]>=len(frozen):return seeds,None
        return seeds,_encode(state)
    def enumerate_page(self,fetch_page,cursor=None):
        policy=POLICIES[self.chain];state=_decode(cursor,self.root_url)
        if len(state["visited"])>self.max_total_pages:raise ValueError("CHAIN_DIRECTORY_TOTAL_PAGE_BUDGET_EXHAUSTED")
        if state["phase"]=="DISCOVER":
            self._discover(fetch_page,state,policy)
            if state["phase"]=="DISCOVER":return [],_encode(state)
        return self._emit(state)
