"""Browser-network discovery for public official hotel inventory contracts.

Input is a HAR-like capture from a normal browser session on an approved official
site. This module does not require or assume a partner API. It inspects browser-visible
XHR/fetch/document JSON responses, rejects non-official hosts and authentication-only
responses, extracts candidate hotel records only when explicit IDs/names/official URLs
are present, and proves pagination/cursor termination before a contract can be frozen.

No endpoint is promoted automatically. Discovery evidence must be stable across at
least two independent captures and the complete normalized inventory SHA must match.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

from .chain_hotel_registry import ChainCode, POLICIES, OfficialPropertySeed, validate_official_seed

XHR_TYPES={"xhr","fetch","document"}
JSON_MIME_TOKENS=("application/json","text/json","+json")
ID_KEYS=("hotelId","hotel_id","hotelID","propertyId","property_id","propertyCode","hotelCode","id")
NAME_KEYS=("hotelName","hotel_name","propertyName","property_name","name")
URL_KEYS=("hotelUrl","hotel_url","propertyUrl","property_url","detailUrl","detail_url","url")
NEXT_KEYS=("nextCursor","next_cursor","cursor","nextPage","next_page","pageNo","page_no","page")
TOTAL_KEYS=("total","totalCount","total_count","hotelCount","hotel_count")
LIST_KEYS=("hotels","hotelList","hotel_list","properties","propertyList","property_list","items","list","records","data")


def _host_allowed(chain:ChainCode,host:str|None)->bool:
    host=str(host or "").lower().rstrip(".")
    return any(host==root or host.endswith("."+root) for root in POLICIES[chain].official_hosts)

def _json(value):
    if isinstance(value,(dict,list)):return value
    if not isinstance(value,str):return None
    try:return json.loads(value)
    except Exception:return None

def _walk(value,path=()):
    yield path,value
    if isinstance(value,dict):
        for k,v in value.items():yield from _walk(v,path+(str(k),))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from _walk(v,path+(str(i),))

def _first(d:dict,keys):
    for key in keys:
        value=d.get(key)
        if value not in (None,""):return value
    return None

def _absolute(base:str,value)->str|None:
    if not value:return None
    text=str(value).strip()
    if text.startswith("//"):text="https:"+text
    if text.startswith("/"):
        p=urlsplit(base);text=f"https://{p.netloc}{text}"
    p=urlsplit(text)
    if p.scheme!="https" or not p.hostname:return None
    return text.split("#",1)[0]

def _candidate_record(chain:ChainCode,base_url:str,d:dict):
    identity=_first(d,ID_KEYS);name=_first(d,NAME_KEYS);url=_absolute(base_url,_first(d,URL_KEYS))
    if identity in (None,"") or not str(name or "").strip() or not url:return None
    if not _host_allowed(chain,urlsplit(url).hostname):return None
    seed=OfficialPropertySeed(chain=chain,official_property_id=str(identity).strip(),name=str(name).strip(),property_url=url,directory_url=base_url,country_code="CN")
    try:validate_official_seed(seed)
    except ValueError:return None
    return seed

def _extract_records(chain:ChainCode,request_url:str,payload)->list[OfficialPropertySeed]:
    by_id={}
    for _,node in _walk(payload):
        if not isinstance(node,dict):continue
        seed=_candidate_record(chain,request_url,node)
        if not seed:continue
        existing=by_id.get(seed.official_property_id)
        if existing and (existing.name!=seed.name or existing.property_url!=seed.property_url):raise ValueError(f"BROWSER_INVENTORY_ID_CONFLICT:{chain.value}:{seed.official_property_id}")
        by_id[seed.official_property_id]=seed
    return [by_id[k] for k in sorted(by_id)]

def _pagination_signals(url:str,payload)->dict:
    query=parse_qs(urlsplit(url).query)
    found={"request_page":None,"request_cursor":None,"response_next":None,"response_total":None}
    for key in ("page","pageNo","page_no","pageIndex","page_index"):
        if key in query and query[key]:found["request_page"]=query[key][-1];break
    for key in ("cursor","pageToken","page_token","nextCursor"):
        if key in query and query[key]:found["request_cursor"]=query[key][-1];break
    for _,node in _walk(payload):
        if not isinstance(node,dict):continue
        if found["response_next"] is None:
            found["response_next"]=_first(node,NEXT_KEYS)
        if found["response_total"] is None:
            found["response_total"]=_first(node,TOTAL_KEYS)
    return found

@dataclass(frozen=True)
class NetworkPageEvidence:
    url:str;response_sha256:str;property_ids:tuple[str,...];pagination:dict

class BrowserNetworkInventoryDiscovery:
    def analyze_capture(self,*,chain:ChainCode,capture:dict)->dict:
        entries=((capture.get("log") or {}).get("entries") if isinstance(capture,dict) else None)
        if not isinstance(entries,list):raise ValueError("BROWSER_NETWORK_CAPTURE_INVALID")
        endpoint_pages={};all_seeds={};rejected_nonofficial=0;json_entries=0
        for entry in entries:
            req=entry.get("request") or {};resp=entry.get("response") or {};url=str(req.get("url") or "");p=urlsplit(url)
            if p.scheme!="https" or not _host_allowed(chain,p.hostname):
                if url:rejected_nonofficial+=1
                continue
            resource_type=str(entry.get("_resourceType") or entry.get("resourceType") or "").lower()
            if resource_type and resource_type not in XHR_TYPES:continue
            status=int(resp.get("status") or 0)
            if status!=200:continue
            content=resp.get("content") or {};mime=str(content.get("mimeType") or "").lower();body=content.get("text")
            if mime and not any(token in mime for token in JSON_MIME_TOKENS) and not str(body or "").lstrip().startswith(("{","[")):continue
            payload=_json(body)
            if payload is None:continue
            json_entries+=1;seeds=_extract_records(chain,url,payload)
            if not seeds:continue
            for seed in seeds:
                existing=all_seeds.get(seed.official_property_id)
                if existing and (existing.name!=seed.name or existing.property_url!=seed.property_url):raise ValueError(f"BROWSER_INVENTORY_ID_CONFLICT:{chain.value}:{seed.official_property_id}")
                all_seeds[seed.official_property_id]=seed
            endpoint=f"{p.scheme}://{p.netloc}{p.path}"
            page=NetworkPageEvidence(url=url,response_sha256=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest(),property_ids=tuple(sorted(x.official_property_id for x in seeds)),pagination=_pagination_signals(url,payload))
            endpoint_pages.setdefault(endpoint,[]).append(page)
        candidates=[]
        for endpoint,pages in endpoint_pages.items():
            unique_ids=set();duplicate_ids=0
            for page in pages:
                for pid in page.property_ids:
                    if pid in unique_ids:duplicate_ids+=1
                    unique_ids.add(pid)
            signals=[p.pagination for p in pages]
            has_pagination=len(pages)>1 and any(x.get("request_page") is not None or x.get("request_cursor") is not None or x.get("response_next") is not None for x in signals)
            terminal=bool(signals) and (signals[-1].get("response_next") in (None,"",False,0) or len(pages[-1].property_ids)==0)
            totals=[x.get("response_total") for x in signals if x.get("response_total") not in (None,"")]
            total_match=True
            if totals:
                try:total_match=int(totals[-1])==len(unique_ids)
                except Exception:total_match=False
            candidates.append({"endpoint":endpoint,"page_count":len(pages),"unique_property_count":len(unique_ids),"duplicate_property_occurrences":duplicate_ids,"has_pagination":has_pagination,"terminal_observed":terminal,"reported_total":totals[-1] if totals else None,"reported_total_matches_unique":total_match,"page_response_sha256":[p.response_sha256 for p in pages],"property_ids":sorted(unique_ids)})
        candidates.sort(key=lambda x:(x["terminal_observed"],x["reported_total_matches_unique"],x["unique_property_count"]),reverse=True)
        normalized=[{"official_property_id":s.official_property_id,"name":s.name,"property_url":s.property_url} for s in sorted(all_seeds.values(),key=lambda x:x.official_property_id)]
        inventory_sha=hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest() if normalized else None
        best=candidates[0] if candidates else None
        return {"chain":chain.value,"official_json_entries":json_entries,"rejected_nonofficial_entries":rejected_nonofficial,"candidate_endpoints":candidates,"best_candidate":best,"property_count":len(normalized),"inventory":normalized,"inventory_sha256":inventory_sha,"pagination_contract_proven":bool(best and best["has_pagination"] and best["terminal_observed"] and best["reported_total_matches_unique"] and best["unique_property_count"]>0)}

    def compare_independent_captures(self,*,chain:ChainCode,captures:list[dict])->dict:
        if len(captures)<2:raise ValueError("BROWSER_INVENTORY_TWO_CAPTURES_REQUIRED")
        reports=[self.analyze_capture(chain=chain,capture=x) for x in captures]
        hashes=[x.get("inventory_sha256") for x in reports]
        stable=bool(hashes[0]) and len(set(hashes))==1
        endpoint_sets=[{x["endpoint"] for x in r["candidate_endpoints"] if x["terminal_observed"]} for r in reports]
        common=set.intersection(*endpoint_sets) if endpoint_sets else set()
        return {"chain":chain.value,"capture_count":len(reports),"stable_inventory_sha":stable,"inventory_sha256":hashes[0] if stable else None,"common_terminal_endpoints":sorted(common),"all_pagination_contracts_proven":all(r["pagination_contract_proven"] for r in reports),"reports":reports,"status":"PASS" if stable and bool(common) and all(r["pagination_contract_proven"] for r in reports) else "HOLD"}

browser_network_inventory_discovery=BrowserNetworkInventoryDiscovery()
