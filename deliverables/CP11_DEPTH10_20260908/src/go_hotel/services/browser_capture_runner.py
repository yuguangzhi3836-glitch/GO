"""Autonomous normal-browser capture runner for public official inventory discovery.

This runner uses a standard browser session, never credentials or partner APIs. It
records browser-visible XHR/fetch/document JSON, scrolls, follows conservative public
inventory UI controls, and stops only after repeated network/DOM quiescence or an
explicit disabled/absent continuation control. The raw capture is compatible with
BrowserNetworkInventoryDiscovery.

Production adapters remain disabled until two independent runs produce the same frozen
inventory SHA and the source contract is explicitly promoted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from .chain_hotel_registry import ChainCode, POLICIES
from .chain_official_source_contracts import contract_for

SAFE_MORE_TEXT=(
    "下一页","下一頁","加载更多","載入更多","查看更多","更多酒店","全部酒店","酒店列表",
    "next","load more","show more","view more","all hotels","hotels",
)
BLOCK_TEXT=("登录","登入","注册","註冊","会员","會員","支付","预订","預訂","book now","reserve","sign in","login")
JSON_MIME=("application/json","text/json","+json")


def _now(): return datetime.now(timezone.utc).isoformat()

def _host_allowed(chain:ChainCode,host:str|None)->bool:
    host=str(host or "").lower().rstrip(".")
    return any(host==root or host.endswith("."+root) for root in POLICIES[chain].official_hosts)


def _safe_entry(chain:ChainCode,url:str)->str:
    p=urlsplit(url)
    if p.scheme!="https" or not p.hostname or not _host_allowed(chain,p.hostname):
        raise ValueError("BROWSER_CAPTURE_ENTRY_NOT_OFFICIAL")
    return url


def _har_entry(response, body_text:str|None):
    request=response.request
    headers=[]
    try:
        for k,v in response.headers.items(): headers.append({"name":str(k),"value":str(v)})
    except Exception: pass
    mime=str(response.headers.get("content-type") or "") if response.headers else ""
    return {
        "startedDateTime":_now(),
        "_resourceType":str(getattr(request,"resource_type","") or ""),
        "request":{"method":request.method,"url":request.url,"headers":[]},
        "response":{"status":response.status,"headers":headers,"content":{"mimeType":mime,"text":body_text}},
    }


@dataclass(frozen=True)
class CaptureResult:
    chain:str
    entry_url:str
    final_url:str
    cycles:int
    json_response_count:int
    termination_reason:str
    capture_path:str
    screenshot_path:str|None


class BrowserCaptureRunner:
    def capture(self,*,chain:ChainCode,output_path:str|Path,entry_url:str|None=None,
                headless:bool=True,max_cycles:int=80,settle_ms:int=1200,actor:str="SYSTEM") -> CaptureResult:
        if chain not in {ChainCode.H_WORLD,ChainCode.ATOUR}:
            raise ValueError("BROWSER_CAPTURE_CHAIN_NOT_SUPPORTED")
        if not 5<=int(max_cycles)<=300: raise ValueError("BROWSER_CAPTURE_MAX_CYCLES_INVALID")
        contract=contract_for(chain)
        url=_safe_entry(chain,entry_url or contract.directory_url)
        output=Path(output_path); output.parent.mkdir(parents=True,exist_ok=True)
        screenshot=output.with_suffix(".png")
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError("PLAYWRIGHT_REQUIRED_FOR_BROWSER_CAPTURE") from exc

        entries=[];seen_response_keys=set();json_count=0
        last_signature=None;stable_cycles=0;termination="MAX_CYCLES"
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=headless,args=["--disable-dev-shm-usage"])
            context=browser.new_context(locale="zh-CN",viewport={"width":1440,"height":1100})
            page=context.new_page()

            def on_response(response):
                nonlocal json_count
                try:
                    p=urlsplit(response.url)
                    if p.scheme!="https" or not _host_allowed(chain,p.hostname): return
                    rtype=str(response.request.resource_type or "").lower()
                    if rtype not in {"xhr","fetch","document"}: return
                    if int(response.status)!=200: return
                    ctype=str(response.headers.get("content-type") or "").lower()
                    body=response.text()
                    if not (any(t in ctype for t in JSON_MIME) or str(body).lstrip().startswith(("{","["))): return
                    key=(response.request.method,response.url,hash(body))
                    if key in seen_response_keys:return
                    seen_response_keys.add(key);entries.append(_har_entry(response,body));json_count+=1
                except Exception:
                    return
            page.on("response",on_response)
            page.goto(url,wait_until="domcontentloaded",timeout=45000)
            try: page.wait_for_load_state("networkidle",timeout=10000)
            except Exception: pass

            for cycle in range(1,int(max_cycles)+1):
                before=len(entries)
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception: pass
                page.wait_for_timeout(int(settle_ms))
                clicked=False
                for label in SAFE_MORE_TEXT:
                    if any(block in label.lower() for block in BLOCK_TEXT): continue
                    try:
                        locator=page.get_by_text(label,exact=False)
                        count=min(locator.count(),8)
                        for i in range(count):
                            el=locator.nth(i)
                            try:
                                if not el.is_visible() or not el.is_enabled(): continue
                                text=(el.inner_text() or "").strip().lower()
                                if any(x.lower() in text for x in BLOCK_TEXT): continue
                                tag=(el.evaluate("e=>e.tagName") or "").lower()
                                if tag not in {"a","button","div","span","li"}: continue
                                el.click(timeout=1500);clicked=True;page.wait_for_timeout(int(settle_ms));break
                            except Exception: continue
                        if clicked:break
                    except Exception:continue
                signature=(page.url,len(entries),page.evaluate("document.body.scrollHeight"))
                if signature==last_signature and len(entries)==before and not clicked:
                    stable_cycles+=1
                else: stable_cycles=0
                last_signature=signature
                if stable_cycles>=3:
                    termination="QUIESCENT_NO_PUBLIC_CONTINUATION"
                    break
            final_url=page.url
            try: page.screenshot(path=str(screenshot),full_page=True)
            except Exception: screenshot=None
            context.close();browser.close()

        capture={"log":{"version":"1.2","creator":{"name":"GO BrowserCaptureRunner","version":"DEPTH10"},"pages":[{"startedDateTime":_now(),"id":"page_1","title":chain.value,"pageTimings":{}}],"entries":entries},"go_capture_meta":{"chain":chain.value,"entry_url":url,"final_url":final_url,"actor":actor,"termination_reason":termination,"json_response_count":json_count}}
        output.write_text(json.dumps(capture,ensure_ascii=False,indent=2),encoding="utf-8")
        return CaptureResult(chain.value,url,final_url,cycle,json_count,termination,str(output),str(screenshot) if screenshot else None)


browser_capture_runner=BrowserCaptureRunner()
