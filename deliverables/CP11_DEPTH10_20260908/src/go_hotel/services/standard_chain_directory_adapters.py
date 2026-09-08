"""Fail-closed official directory adapters backed by per-chain source contracts.

Adapters may only enumerate from a contract-approved official entrypoint. Chains
whose full official directory is not yet verified stay HOLD; a generic homepage or
third-party listing can never silently become nationwide inventory truth.
"""
from __future__ import annotations
import base64, hashlib, json, os, re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from .chain_hotel_registry import ChainCode, ChainDirectoryAdapter, OfficialPropertySeed, POLICIES
from .chain_official_source_contracts import assert_directory_production_ready, validate_contract_document

_GENERIC={"hotel","view hotel","view details","book now","learn more","reserve","查看酒店","查看详情","立即预订","预订","了解更多"}
def _norm(value): return re.sub(r"\s+"," ",str(value or "")).strip()
class _Links(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.href=None; self.text=[]; self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()!="a" or self.href is not None:return
        href=str({str(k).lower():(v or "") for k,v in attrs}.get("href") or "").strip()
        if href:self.href=href; self.text=[]
    def handle_data(self,data):
        if self.href is not None:self.text.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=="a" and self.href is not None:self.links.append((self.href,_norm(" ".join(self.text)))); self.href=None; self.text=[]
def _host_ok(host,roots):
    host=str(host or "").lower().rstrip("."); return bool(host) and any(host==root or host.endswith("."+root) for root in roots)
def _fetch(fetch_page,url):
    value=fetch_page(url)
    if isinstance(value,str):return url,value
    if isinstance(value,tuple) and len(value)>=2 and isinstance(value[0],str) and isinstance(value[1],str):return value[0],value[1]
    raise ValueError("CHAIN_DIRECTORY_FETCH_RESULT_INVALID")
def _decode(cursor):
    if not cursor:return {"offset":0,"snapshot_sha256":None}
    try:value=json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")+b"="*(-len(cursor)%4)).decode("utf-8"))
    except Exception as exc:raise ValueError("CHAIN_DIRECTORY_CURSOR_INVALID") from exc
    if not isinstance(value,dict) or not isinstance(value.get("offset"),int) or value["offset"]<0:raise ValueError("CHAIN_DIRECTORY_CURSOR_INVALID")
    return value
def _encode(offset,snapshot):
    raw=json.dumps({"offset":int(offset),"snapshot_sha256":snapshot},sort_keys=True,separators=(",",":")).encode(); return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

class ContractDirectoryAdapter(ChainDirectoryAdapter):
    chain: ChainCode
    env_directory_url: str|None=None
    country_code: str|None=None
    def __init__(self,directory_url=None,*,page_size=50):
        if not 1<=int(page_size)<=100:raise ValueError("CHAIN_DIRECTORY_PAGE_SIZE_INVALID")
        contract=assert_directory_production_ready(self.chain)
        configured=os.getenv(self.env_directory_url or "") if self.env_directory_url else None
        self.directory_url=directory_url or configured or contract.directory_url; self.page_size=int(page_size)
    def extract_property_identity(self,url,label): raise NotImplementedError
    def _inventory(self,fetch_page):
        final,html=_fetch(fetch_page,self.directory_url); policy=POLICIES[self.chain]; parsed=urlsplit(final)
        if parsed.scheme!="https" or not _host_ok(parsed.hostname,policy.official_hosts):raise ValueError("CHAIN_DIRECTORY_FINAL_URL_NOT_OFFICIAL")
        validate_contract_document(self.chain,final_url=final,text=html)
        snapshot=hashlib.sha256(html.encode("utf-8")).hexdigest(); parser=_Links(); parser.feed(html); by_id={}
        for href,label in parser.links:
            absolute=urljoin(final,href); u=urlsplit(absolute)
            if u.scheme!="https" or not _host_ok(u.hostname,policy.official_hosts):continue
            identity=self.extract_property_identity(absolute,_norm(label))
            if not identity:continue
            property_id,name=identity
            if not name or name.casefold() in _GENERIC or len(name)<3:continue
            current=by_id.get(property_id)
            if current and current["name"].casefold()!=name.casefold():raise ValueError(f"CHAIN_DIRECTORY_PROPERTY_NAME_CONFLICT:{self.chain.value}:{property_id}")
            by_id[property_id]={"name":name,"url":absolute.split("#",1)[0]}
        if not by_id:raise ValueError(f"CHAIN_DIRECTORY_NO_PROPERTIES_FOUND:{self.chain.value}")
        seeds=[OfficialPropertySeed(chain=self.chain,official_property_id=pid,name=item["name"],property_url=item["url"],directory_url=final,country_code=self.country_code) for pid,item in sorted(by_id.items())]
        return self.validate(seeds),snapshot
    def enumerate_page(self,fetch_page,cursor=None):
        state=_decode(cursor); seeds,snapshot=self._inventory(fetch_page)
        if state.get("snapshot_sha256") and state["snapshot_sha256"]!=snapshot:raise ValueError(f"CHAIN_DIRECTORY_SNAPSHOT_CHANGED:{self.chain.value}")
        offset=state["offset"]
        if offset>len(seeds):raise ValueError("CHAIN_DIRECTORY_CURSOR_OUT_OF_RANGE")
        page=seeds[offset:offset+self.page_size]; next_offset=offset+len(page)
        return page,(_encode(next_offset,snapshot) if next_offset<len(seeds) else None)

class MarriottDirectoryAdapter(ContractDirectoryAdapter):
    chain=ChainCode.MARRIOTT; env_directory_url="GO_MARRIOTT_DIRECTORY_URL"
    def extract_property_identity(self,url,label):
        path=urlsplit(url).path
        for pattern in (r"/(?:[a-z]{2}-[a-z]{2}/)?hotels/([a-z0-9]{3,12})-[^/]+(?:/|$)",r"/hotels/travel/([a-z0-9]{3,12})(?:/|$)"):
            m=re.search(pattern,path,re.I)
            if m:return m.group(1).upper(),label
        return None

class ShangriLaDirectoryAdapter(ContractDirectoryAdapter):
    chain=ChainCode.SHANGRI_LA; env_directory_url="GO_SHANGRILA_DIRECTORY_URL"; country_code="CN"
    def extract_property_identity(self,url,label):
        m=re.match(r"^/(?:cn/|en/)?([a-z0-9-]{2,40})/([a-z0-9-]{3,64})/?$",urlsplit(url).path,re.I)
        return ((m.group(1)+"__"+m.group(2)).upper(),label) if m else None

class HiltonDirectoryAdapter(ContractDirectoryAdapter):
    chain=ChainCode.HILTON; env_directory_url="GO_HILTON_DIRECTORY_URL"
    def extract_property_identity(self,url,label):
        m=re.search(r"/(?:[a-z]{2}/)?hotels/([a-z0-9]{4,18})-[^/]+(?:/|$)",urlsplit(url).path,re.I)
        return (m.group(1).upper(),label) if m else None

class IHGDirectoryAdapter(ContractDirectoryAdapter):
    chain=ChainCode.IHG; env_directory_url="GO_IHG_DIRECTORY_URL"
    def extract_property_identity(self,url,label):
        m=re.search(r"/hotels/[a-z]{2}/[a-z]{2}/[^/]+/[^/]+/([a-z0-9]{4,14})/hoteldetail(?:/|$)",urlsplit(url).path,re.I)
        return (m.group(1).upper(),label) if m else None

class HWorldDirectoryAdapter(ContractDirectoryAdapter):
    chain=ChainCode.H_WORLD; env_directory_url="GO_HWORLD_DIRECTORY_URL"; country_code="CN"
    def extract_property_identity(self,url,label):
        raise ValueError("CHAIN_FULL_DIRECTORY_CONTRACT_HOLD:H_WORLD")

class AtourDirectoryAdapter(ContractDirectoryAdapter):
    chain=ChainCode.ATOUR; env_directory_url="GO_ATOUR_DIRECTORY_URL"; country_code="CN"
    def extract_property_identity(self,url,label):
        raise ValueError("CHAIN_FULL_DIRECTORY_CONTRACT_HOLD:ATOUR")
