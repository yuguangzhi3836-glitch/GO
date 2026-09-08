"""Chain-first autonomous hotel discovery contracts.

This module deliberately separates enumerating a group's official property catalog
from capturing an individual hotel's facts. Adapters must return verifiable official
seeds; they may not guess identities from page titles or accept third-party domains.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib
from urllib.parse import urlsplit

class ChainCode(str,Enum):
    HYATT="HYATT";MARRIOTT="MARRIOTT";SHANGRI_LA="SHANGRI_LA";HILTON="HILTON";IHG="IHG";H_WORLD="H_WORLD";ATOUR="ATOUR"

CHAIN_EXECUTION_ORDER=(ChainCode.HYATT,ChainCode.MARRIOTT,ChainCode.SHANGRI_LA,ChainCode.HILTON,ChainCode.IHG,ChainCode.H_WORLD,ChainCode.ATOUR)

@dataclass(frozen=True)
class ChainPolicy:
    code:ChainCode;official_hosts:tuple[str,...];max_domain_concurrency:int;request_budget_per_minute:int

POLICIES={
    ChainCode.HYATT:ChainPolicy(ChainCode.HYATT,("hyatt.com","www.hyatt.com"),3,30),
    ChainCode.MARRIOTT:ChainPolicy(ChainCode.MARRIOTT,("marriott.com","www.marriott.com"),3,30),
    ChainCode.SHANGRI_LA:ChainPolicy(ChainCode.SHANGRI_LA,("shangri-la.com","www.shangri-la.com"),3,30),
    ChainCode.HILTON:ChainPolicy(ChainCode.HILTON,("hilton.com","www.hilton.com"),3,30),
    ChainCode.IHG:ChainPolicy(ChainCode.IHG,("ihg.com","www.ihg.com"),3,30),
    ChainCode.H_WORLD:ChainPolicy(ChainCode.H_WORLD,("hworld.com","www.hworld.com"),3,30),
    # atour.com is not Atour Lifestyle's consumer/corporate domain and must never
    # be accepted as an official hotel source. Atour's verified corporate/IR domain
    # is under yaduo.com; any future booking/app subdomain must remain under this root
    # or be separately evidence-approved before it can enter POLICIES.
    ChainCode.ATOUR:ChainPolicy(ChainCode.ATOUR,("yaduo.com","www.yaduo.com","ir.yaduo.com"),3,30),
}

@dataclass(frozen=True)
class OfficialPropertySeed:
    chain:ChainCode;official_property_id:str;name:str;property_url:str;directory_url:str;country_code:str|None=None;city:str|None=None
    @property
    def idempotency_key(self)->str:
        raw=f"{self.chain.value}\n{self.official_property_id.strip()}".encode("utf-8");return "chain_property_"+hashlib.sha256(raw).hexdigest()[:32]

def _host_allowed(host:str,allowed:tuple[str,...])->bool:
    host=host.lower().rstrip(".");return any(host==root or host.endswith("."+root) for root in allowed)

def validate_official_seed(seed:OfficialPropertySeed)->OfficialPropertySeed:
    if not seed.official_property_id.strip() or not seed.name.strip():raise ValueError("CHAIN_PROPERTY_IDENTITY_REQUIRED")
    policy=POLICIES[seed.chain]
    for value in (seed.property_url,seed.directory_url):
        parsed=urlsplit(value)
        if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:raise ValueError("CHAIN_OFFICIAL_HTTPS_URL_REQUIRED")
        if not _host_allowed(parsed.hostname,policy.official_hosts):raise ValueError("CHAIN_SOURCE_HOST_NOT_ALLOWED")
    return seed

class ChainDirectoryAdapter:
    chain:ChainCode
    def enumerate_page(self,fetch_page,cursor:str|None=None)->tuple[list[OfficialPropertySeed],str|None]:raise NotImplementedError
    def validate(self,seeds:list[OfficialPropertySeed])->list[OfficialPropertySeed]:
        seen=set();out=[]
        for seed in seeds:
            validate_official_seed(seed)
            if seed.chain!=self.chain:raise ValueError("CHAIN_ADAPTER_SEED_MISMATCH")
            if seed.idempotency_key in seen:continue
            seen.add(seed.idempotency_key);out.append(seed)
        return out
