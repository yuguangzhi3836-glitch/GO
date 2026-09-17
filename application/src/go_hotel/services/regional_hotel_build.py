from __future__ import annotations
from go_hotel.services import catalog_scope

from datetime import datetime, timezone
import json
import os
import re
import time
import uuid
from urllib.parse import quote, urlencode

from sqlalchemy import select

from go_hotel.db.models import HotelAutoPageEventRow, HotelCanonicalProfileRow
from go_hotel.db.session import SessionLocal
from go_hotel.queue.durable_regional import DurableRegionalQueue, guard_current, current_reference
from go_hotel.autonomy.durable import digest, insert_once, transaction
from go_hotel.services.hotel_discovery_orchestrator import hotel_discovery_orchestrator_service as discovery
from go_hotel.services.hotel_infrastructure_p0 import hotel_infrastructure_p0_service as infra_p0, admission as tier_admission

TOPIC = "hotel-regional-build"

# Province-level queue roots. Cities are discovered from configured, authorized providers.
CN_PROVINCES = [
    "北京市","天津市","河北省","山西省","内蒙古自治区","辽宁省","吉林省","黑龙江省",
    "上海市","江苏省","浙江省","安徽省","福建省","江西省","山东省","河南省","湖北省",
    "湖南省","广东省","广西壮族自治区","海南省","重庆市","四川省","贵州省","云南省",
    "西藏自治区","陕西省","甘肃省","青海省","宁夏回族自治区","新疆维吾尔自治区",
]
MUNICIPALITIES = {"北京市","天津市","上海市","重庆市"}

OSM_BOOTSTRAP_CITY_ALLOWLIST = {"哈尔滨市"}
OSM_DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
OSM_FALLBACK_ENDPOINT = "https://overpass.kumi.systems/api/interpreter"
REGIONAL_PROVIDER_MAX_ATTEMPTS = max(1, min(int(os.getenv("GO_HOTEL_REGION_DISCOVERY_PROVIDER_MAX_ATTEMPTS", "2")), 4))
NATIONAL_TIER_SEQUENCE = [5,4,3,2,1,0]


def now():
    return datetime.now(timezone.utc)


def ident(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"

def _norm(value) -> str:
    text=str(value or "").strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+","",text)


def _candidate_key(candidate: dict) -> tuple:
    external_ids=candidate.get("external_ids") if isinstance(candidate.get("external_ids"),dict) else {}
    stable=tuple(sorted((str(k),str(v)) for k,v in external_ids.items() if str(v or "").strip()))
    external=str(candidate.get("external_hotel_id") or "").strip()
    if stable or external:
        return ("external",stable,external)
    lat=candidate.get("latitude"); lon=candidate.get("longitude")
    try:
        geo=(round(float(lat),4),round(float(lon),4)) if lat is not None and lon is not None else None
    except Exception:
        geo=None
    return ("facts",_norm(candidate.get("name") or candidate.get("name_zh")),_norm(candidate.get("address")),geo)


def _dedupe_candidates(items: list[dict]) -> list[dict]:
    out=[]; seen=set()
    for item in items:
        key=_candidate_key(item)
        if key in seen:
            continue
        seen.add(key); out.append(item)
    return out

def _star_tier(candidate: dict) -> int:
    return int(tier_admission(candidate).get("build_tier") or 0)

def _tier_name(tier: int) -> str:
    return {5:"全国五星级优先",4:"全国四星级",3:"全国三星级",2:"全国二星级",1:"全国一星级",0:"全国未评级与长尾"}.get(int(tier),"全国未评级与长尾")

def _filter_tier(candidates: list[dict], tier: int | None) -> list[dict]:
    if tier is None:
        return candidates
    return [x for x in candidates if _star_tier(x)==int(tier)]

def _error_code(exc: Exception) -> str:
    text=str(exc or "")
    low=text.lower()
    if "timed out" in low or "timeout" in low:
        return "PROVIDER_TIMEOUT"
    if "dns" in low:
        return "PROVIDER_DNS"
    if "private_or_special" in low or "ssrf" in low:
        return "PROVIDER_NETWORK_POLICY"
    if "response_not_json" in low or "items_required" in low or "elements_required" in low:
        return "PROVIDER_SCHEMA"
    return "PROVIDER_ERROR"



def event(event_type: str, evidence: dict, actor: str = "SYSTEM", hotel_id: str | None = None):
    with transaction(SessionLocal) as s:
        guard_current(s)
        s.add(HotelAutoPageEventRow(
            hotel_auto_page_event_id=ident("hape"), hotel_id=hotel_id,
            event_type=event_type, evidence_json={**evidence, **current_reference()}, actor=actor, created_at=now(),
        ))
        s.commit()


def _providers() -> list[dict]:
    out=[]
    raw = (os.getenv("GO_HOTEL_REGION_DISCOVERY_PROVIDERS_JSON") or "").strip()
    if raw:
        try:
            value = json.loads(raw)
        except Exception as exc:
            raise ValueError("REGIONAL_DISCOVERY_PROVIDER_CONFIG_INVALID") from exc
        if not isinstance(value, list):
            raise ValueError("REGIONAL_DISCOVERY_PROVIDER_CONFIG_INVALID")
        for p in value:
            if not isinstance(p, dict) or not p.get("key"):
                continue
            p=dict(p)
            p.setdefault("type","HTTP_JSON")
            if p["type"] == "HTTP_JSON" and (not p.get("cities_url_template") or not p.get("hotels_url_template")):
                continue
            out.append(p)
    if str(os.getenv("GO_HOTEL_REGION_DISCOVERY_BOOTSTRAP_OSM") or "").strip().lower() in {"1","true","yes","on"}:
        configured=(os.getenv("GO_HOTEL_REGION_DISCOVERY_OSM_ENDPOINTS") or "").strip()
        endpoints=[x.strip() for x in configured.split(",") if x.strip()] if configured else []
        single=(os.getenv("GO_HOTEL_REGION_DISCOVERY_OSM_ENDPOINT") or "").strip()
        if single and single not in endpoints:
            endpoints.insert(0,single)
        if not endpoints:
            endpoints=[OSM_DEFAULT_ENDPOINT,OSM_FALLBACK_ENDPOINT]
        out.append({
            "key":"osm-overpass-harbin-bootstrap",
            "type":"OSM_OVERPASS_BOOTSTRAP",
            "endpoint":endpoints[0],
            "endpoints":endpoints,
            "scope":"HARBIN_FIRST_CITY_ONLY",
        })
    return out


def _provider_summary() -> dict:
    providers=_providers()
    production=[p for p in providers if p.get("type") != "OSM_OVERPASS_BOOTSTRAP"]
    bootstrap=[p for p in providers if p.get("type") == "OSM_OVERPASS_BOOTSTRAP"]
    return {
        "configured":bool(providers),
        "provider_count":len(providers),
        "production_provider_count":len(production),
        "bootstrap_provider_count":len(bootstrap),
        "harbin_bootstrap_ready":bool(bootstrap),
        "national_ready":bool(production),
        "providers":[{"key":p.get("key"),"type":p.get("type"),"scope":p.get("scope") or "REGIONAL"} for p in providers],
    }


def _format_url(template: str, *, country: str, province: str | None = None, city: str | None = None) -> str:
    return str(template).format(
        country=quote(country or "", safe=""), province=quote(province or "", safe=""), city=quote(city or "", safe="")
    )


def _fetch_items(url: str) -> list[dict]:
    # Reuse RC11.1 SSRF/private-network hardening and DNS rebinding controls.
    final, body, _, _ = discovery._fetch_html(url, timeout_seconds=12.0, allow_json=True)
    try:
        obj = json.loads(body)
    except Exception as exc:
        raise ValueError("REGIONAL_DISCOVERY_PROVIDER_RESPONSE_NOT_JSON") from exc
    items = obj.get("items") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        raise ValueError("REGIONAL_DISCOVERY_PROVIDER_ITEMS_REQUIRED")
    return [x for x in items if isinstance(x, dict)]


def _osm_address(tags: dict) -> str | None:
    full=str(tags.get("addr:full") or "").strip()
    if full:
        return full
    parts=[tags.get("addr:province"),tags.get("addr:city"),tags.get("addr:district"),tags.get("addr:street"),tags.get("addr:housenumber")]
    text="".join(str(x).strip() for x in parts if str(x or "").strip())
    return text or None


def _osm_overpass_items(provider: dict, *, city: str | None) -> list[dict]:
    city=str(city or "").strip()
    if city not in OSM_BOOTSTRAP_CITY_ALLOWLIST:
        raise ValueError("OSM_BOOTSTRAP_CITY_NOT_ALLOWED")
    endpoints=provider.get("endpoints") if isinstance(provider.get("endpoints"),list) else [provider.get("endpoint") or OSM_DEFAULT_ENDPOINT]
    endpoints=[str(x).strip() for x in endpoints if str(x or "").strip()]
    if not endpoints:
        endpoints=[OSM_DEFAULT_ENDPOINT]
    for endpoint in endpoints:
        if not endpoint.startswith("https://"):
            raise ValueError("OSM_BOOTSTRAP_HTTPS_REQUIRED")
    query=(
        '[out:json][timeout:45];'
        'area["boundary"="administrative"]["name"="'+city+'"]->.searchArea;'
        '(nwr["tourism"~"^(hotel|resort|motel)$"](area.searchArea););'
        'out center tags;'
    )
    body=None; last_exc=None
    for endpoint in endpoints:
        for attempt in range(1,REGIONAL_PROVIDER_MAX_ATTEMPTS+1):
            url=endpoint + ("&" if "?" in endpoint else "?") + urlencode({"data":query})
            try:
                _, body, _, _ = discovery._fetch_html(url, timeout_seconds=55.0, allow_json=True)
                last_exc=None
                break
            except Exception as exc:
                last_exc=exc
                if attempt < REGIONAL_PROVIDER_MAX_ATTEMPTS:
                    time.sleep(min(0.5*attempt,1.5))
        if body is not None:
            break
    if body is None:
        raise ValueError(f"OSM_BOOTSTRAP_PROVIDER_EXHAUSTED:{_error_code(last_exc or Exception('unknown'))}:{last_exc}")
    try:
        obj=json.loads(body)
    except Exception as exc:
        raise ValueError("OSM_BOOTSTRAP_RESPONSE_NOT_JSON") from exc
    elements=obj.get("elements") if isinstance(obj,dict) else None
    if not isinstance(elements,list):
        raise ValueError("OSM_BOOTSTRAP_ELEMENTS_REQUIRED")
    out=[]
    for el in elements:
        if not isinstance(el,dict):
            continue
        tags=el.get("tags") if isinstance(el.get("tags"),dict) else {}
        name=str(tags.get("name:zh") or tags.get("name") or tags.get("name:en") or "").strip()
        if not name:
            continue
        typ=str(el.get("type") or "node")
        oid=str(el.get("id") or "").strip()
        center=el.get("center") if isinstance(el.get("center"),dict) else {}
        lat=el.get("lat") if el.get("lat") is not None else center.get("lat")
        lon=el.get("lon") if el.get("lon") is not None else center.get("lon")
        payload={
            "name":name,
            "name_zh":tags.get("name:zh") or tags.get("name"),
            "name_en":tags.get("name:en"),
            "address":_osm_address(tags),
            "latitude":lat,
            "longitude":lon,
            "website":tags.get("website") or tags.get("contact:website"),
            "phone":tags.get("phone") or tags.get("contact:phone"),
            "stars":tags.get("stars"),
            "rooms":tags.get("rooms"),
            "osm_tourism":tags.get("tourism"),
            "source_attribution":"OpenStreetMap contributors",
        }
        external=f"osm:{typ}/{oid}" if oid else f"osm:{name}"
        source_url=f"https://www.openstreetmap.org/{typ}/{oid}" if oid else None
        out.append({
            "name":name,
            "address":payload.get("address"),
            "provider_key":provider.get("key"),
            "external_hotel_id":external,
            "external_ids":{"osm":external},
            "rights_status":"PUBLIC_BUSINESS_FACT",
            "confidence_bps":6500,
            "source_hints":[{
                "kind":"MAP_DIRECTORY",
                "source_key":"map:openstreetmap",
                "external_hotel_id":external,
                "url":source_url,
                "rights_status":"PUBLIC_BUSINESS_FACT",
                "confidence_bps":6500,
                "payload":payload,
            }],
        })
    return out


def _provider_items(kind: str, *, country: str, province: str | None = None, city: str | None = None) -> list[dict]:
    providers = _providers()
    if not providers:
        raise ValueError("REGIONAL_DISCOVERY_PROVIDER_NOT_CONFIGURED")
    merged=[]
    failures=[]
    for p in providers:
        try:
            ptype=p.get("type") or "HTTP_JSON"
            if ptype == "OSM_OVERPASS_BOOTSTRAP":
                if kind != "hotels":
                    continue
                items=_osm_overpass_items(p,city=city)
            else:
                template = p["cities_url_template"] if kind == "cities" else p["hotels_url_template"]
                url = _format_url(template, country=country, province=province, city=city)
                items=_fetch_items(url)
            for item in items:
                item = dict(item)
                item.setdefault("provider_key", p["key"])
                merged.append(item)
        except Exception as exc:
            failures.append({"provider_key":p.get("key"),"error":str(exc)})
    merged=_dedupe_candidates(merged)
    if not merged and failures:
        raise ValueError("REGIONAL_DISCOVERY_ALL_PROVIDERS_FAILED:"+json.dumps(failures,ensure_ascii=False))
    return merged


def _queue() -> DurableRegionalQueue:
    return DurableRegionalQueue(SessionLocal)


def enqueue(payload: dict, *, initial_events=(), supersedes=None):
    # Parent replay keeps child identity, even after a crash between fan-out and ACK.
    identity = {k: payload.get(k) for k in ('run_id','task','tier','province','city','candidate_key','retry_generation')}
    mid = 'hrbq_' + digest(identity)[:56]
    stage = payload.get('task')
    event_type = 'REGIONAL_BUILD_ENQUEUED' if stage == 'ROOT' else f'REGIONAL_BUILD_{stage}_ENQUEUED'
    evidence = {k: payload.get(k) for k in ('run_id','province','city','tier','candidate_key')}
    evidence.update(message_id=mid, name=(payload.get('seed') or {}).get('name'))
    def record_events(session, message_id):
        for kind, details in (*initial_events, (event_type, evidence)):
            values = dict(hotel_auto_page_event_id='hape_' + digest([message_id, kind])[:56],
                          hotel_id=None, event_type=kind, evidence_json=details,
                          actor=payload.get('actor') or 'SYSTEM', created_at=now())
            insert_once(session, HotelAutoPageEventRow, values, ['hotel_auto_page_event_id'])
    return _queue().enqueue(TOPIC, mid, payload, on_create=record_events, supersedes=supersedes)


def _run_events(run_id: str) -> list[HotelAutoPageEventRow]:
    with SessionLocal() as s:
        rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type.like("REGIONAL_BUILD_%")).order_by(HotelAutoPageEventRow.created_at.asc())).all()
        rows=catalog_scope.visible_events(s,rows)
        return [r for r in rows if (r.evidence_json or {}).get("run_id") == run_id]


class RegionalHotelBuildService:
    def start(self, *, mode: str, actor: str, country: str = "CN", province: str | None = None, city: str | None = None, tier: int | None = None, target_name: str | None = None) -> dict:
        with SessionLocal() as s:
            catalog_scope.require_seed(s,{"name":target_name})
        mode=str(mode or "").upper()
        if mode not in {"NATIONAL","REGION","NATIONAL_TIERED"}:
            raise ValueError("REGIONAL_BUILD_MODE_INVALID")
        if mode == "REGION" and not (province or city):
            raise ValueError("REGIONAL_BUILD_TARGET_REQUIRED")
        summary=_provider_summary()
        if not summary["configured"]:
            raise ValueError("REGIONAL_DISCOVERY_PROVIDER_NOT_CONFIGURED")
        if mode in {"NATIONAL","NATIONAL_TIERED"} and not summary["national_ready"]:
            raise ValueError("NATIONAL_DISCOVERY_PROVIDER_REQUIRED")
        if mode == "REGION" and city and city not in OSM_BOOTSTRAP_CITY_ALLOWLIST and not summary["production_provider_count"]:
            raise ValueError("REGIONAL_DISCOVERY_PROVIDER_NOT_CONFIGURED_FOR_TARGET")
        run_id=ident("hrun")
        first_tier=5 if mode=="NATIONAL_TIERED" else (int(tier) if tier is not None else None)
        if first_tier not in {None,4,5}: raise ValueError("REGIONAL_BUILD_P0_TIER_ONLY_4_OR_5")
        payload={"run_id":run_id,"mode":mode,"country":country,"province":province,"city":city,"tier":first_tier,"tier_name":_tier_name(first_tier) if first_tier is not None else None,"state":"QUEUED","target_name":target_name}
        task={"run_id":run_id,"task":"ROOT","mode":mode,"country":country,"province":province,"city":city,"actor":actor,"tier":first_tier,"target_name":target_name}
        mid=enqueue(task, initial_events=(("REGIONAL_BUILD_CREATED", payload),))
        return {**payload,"message_id":mid,"provider":summary}

    def _process_root(self, p: dict):
        run_id=p["run_id"]; actor=p.get("actor") or "SYSTEM"; country=p.get("country") or "CN"
        provinces = [p.get("province")] if p.get("province") else (CN_PROVINCES if p.get("mode") in {"NATIONAL","NATIONAL_TIERED"} else [])
        if p.get("city"):
            enqueue({**p,"task":"CITY","province":p.get("province"),"city":p["city"]})
            return
        for province in provinces:
            enqueue({**p,"task":"PROVINCE","province":province,"city":None})

    def _process_province(self, p: dict):
        run_id=p["run_id"]; actor=p.get("actor") or "SYSTEM"; province=p.get("province"); country=p.get("country") or "CN"
        event("REGIONAL_BUILD_PROVINCE_STARTED", {"run_id":run_id,"province":province,"tier":p.get("tier")}, actor)
        try:
            if province in MUNICIPALITIES:
                cities=[{"name":province}]
            else:
                cities=_provider_items("cities",country=country,province=province)
            names=[]
            for c in cities:
                name=str(c.get("name") or c.get("city") or "").strip()
                if not name or name in names: continue
                names.append(name)
                enqueue({**p,"task":"CITY","city":name})
            event("REGIONAL_BUILD_PROVINCE_FINISHED", {"run_id":run_id,"province":province,"city_count":len(names),"tier":p.get("tier"),"state":"COMPLETED"}, actor)
        except Exception as exc:
            event("REGIONAL_BUILD_FAILURE", {"run_id":run_id,"scope":"PROVINCE","province":province,"error":str(exc),"retryable":True,"tier":p.get("tier")}, actor)
            return {"state":"FAILED", "code":_error_code(exc), "retryable":True}

    def _seed_from_candidate(self, candidate: dict, *, country: str, province: str | None, city: str) -> dict:
        name=str(candidate.get("name") or candidate.get("name_zh") or "").strip()
        if not name:
            raise ValueError("REGIONAL_DISCOVERY_HOTEL_NAME_REQUIRED")
        hints=candidate.get("source_hints") if isinstance(candidate.get("source_hints"),list) else []
        if not hints:
            # Provider can return an authoritative structured payload; the existing discovery pipeline
            # still snapshots it and applies Canonical/entity-resolution rules.
            payload={k:v for k,v in candidate.items() if k not in {"source_hints","provider_key","external_hotel_id"}}
            hints=[{
                "kind":"CONTENT_PROVIDER","source_key":f"region:{candidate.get('provider_key') or 'provider'}",
                "external_hotel_id":candidate.get("external_hotel_id") or candidate.get("id") or name,
                "rights_status":candidate.get("rights_status") or "AUTHORIZED",
                "confidence_bps":int(candidate.get("confidence_bps") or 8000),"payload":payload,
            }]
        return {"name":name,"address":candidate.get("address"),"country":country,"province":province,"city":city,"external_ids":candidate.get("external_ids") or {},"source_hints":hints}

    def _process_city(self, p: dict):
        run_id=p["run_id"]; actor=p.get("actor") or "SYSTEM"; country=p.get("country") or "CN"; province=p.get("province"); city=p.get("city")
        tier=p.get("tier")
        event("REGIONAL_BUILD_CITY_STARTED", {"run_id":run_id,"province":province,"city":city,"tier":tier,"tier_name":_tier_name(tier) if tier is not None else None}, actor)
        try:
            raw=_provider_items("hotels",country=country,province=province,city=city)
            deduped=_dedupe_candidates(raw)
            candidates=_filter_tier(deduped,tier)
            target_name=str(p.get("target_name") or "").strip()
            if target_name:
                target_norm=_norm(target_name)
                candidates=[c for c in candidates if target_norm in _norm(c.get("name") or c.get("name_zh")) or _norm(c.get("name") or c.get("name_zh")) in target_norm]
            queued=0
            for c in candidates:
                seed=self._seed_from_candidate(c,country=country,province=province,city=city)
                candidate_key=json.dumps(_candidate_key(c),ensure_ascii=False,sort_keys=True,default=str)
                mid=enqueue({
                    "run_id":run_id,"task":"HOTEL","mode":p.get("mode") or "REGION","country":country,
                    "province":province,"city":city,"actor":actor,"seed":seed,"candidate_key":candidate_key,"tier":tier,
                    "retry_generation":p.get("retry_generation"),"target_name":p.get("target_name"),
                })
                queued += 1
            event("REGIONAL_BUILD_CITY_DISCOVERY_FINISHED", {
                "run_id":run_id,"province":province,"city":city,"state":"PROCESSING",
                "tier":tier,"tier_name":_tier_name(tier) if tier is not None else None,
                "discovered":len(raw),"deduped":len(deduped),"tier_matched":len(candidates),"queued":queued,
                "duplicates_removed":max(0,len(raw)-len(deduped)),
            }, actor)
            if p.get("mode")=="NATIONAL_TIERED" and queued==0:
                self._maybe_advance_tier(run_id,actor)
        except Exception as exc:
            code=_error_code(exc)
            event("REGIONAL_BUILD_FAILURE", {
                "run_id":run_id,"scope":"CITY","province":province,"city":city,"tier":tier,
                "error_code":code,"error":str(exc),"retryable":code in {"PROVIDER_TIMEOUT","PROVIDER_DNS","PROVIDER_ERROR"},
                "operator_action_required":code not in {"PROVIDER_TIMEOUT","PROVIDER_DNS"},
            }, actor)
            event("REGIONAL_BUILD_CITY_FINISHED", {
                "run_id":run_id,"province":province,"city":city,"state":"FAILED",
                "discovered":0,"canonical":0,"pages":0,"conflicts":0,"failures":1,
            }, actor)
            return {"state":"FAILED", "code":code, "retryable":code in {"PROVIDER_TIMEOUT","PROVIDER_DNS","PROVIDER_ERROR"}}

    def _process_hotel(self, p: dict):
        run_id=p["run_id"]; actor=p.get("actor") or "SYSTEM"; province=p.get("province"); city=p.get("city")
        seed=p.get("seed") if isinstance(p.get("seed"),dict) else {}
        candidate_key=p.get("candidate_key")
        event("REGIONAL_BUILD_HOTEL_STARTED", {
            "run_id":run_id,"province":province,"city":city,"candidate_key":candidate_key,"name":seed.get("name"),
        }, actor)
        try:
            reg=discovery.register_seed(seed,actor)
            result=discovery.run_job(reg["job_id"],actor,max_retries=2)
            hotel_id=result.get("hotel_id")
            page=False; conflict_fields=[]
            if hotel_id:
                with SessionLocal() as s:
                    prof=s.get(HotelCanonicalProfileRow,hotel_id)
                    if prof:
                        page=prof.page_state == "PUBLISHED"
                        conflict_fields=[k for k,v in (prof.field_provenance_json or {}).items() if isinstance(v,dict) and v.get("conflict_state")=="REVIEW_REQUIRED"]
            gate=None; graph=None
            if hotel_id:
                gate=infra_p0.completeness_gate(hotel_id,tier=int(p.get("tier") or 0))
                graph=infra_p0.project_to_travel_graph(hotel_id)
            if conflict_fields:
                event("REGIONAL_BUILD_CONFLICT", {
                    "run_id":run_id,"province":province,"city":city,"hotel_id":hotel_id,
                    "name":seed.get("name"),"fields":conflict_fields,"operator_action_required":True,
                }, actor, hotel_id)
            event("REGIONAL_BUILD_HOTEL_FINISHED", {
                "run_id":run_id,"province":province,"city":city,"candidate_key":candidate_key,
                "name":seed.get("name"),"hotel_id":hotel_id,"page":bool(page),"tier":p.get("tier"),
                "conflicts":len(conflict_fields),"failures":int(result.get("failure_count") or 0),
                "completeness_gate":gate,"travel_graph":graph,
                "state":"COMPLETED" if hotel_id and page and gate and gate.get("passed") and not result.get("failure_count") else "NEEDS_ENRICHMENT",
            }, actor, hotel_id)
            self._maybe_advance_tier(run_id,actor)
        except Exception as exc:
            code=_error_code(exc)
            event("REGIONAL_BUILD_FAILURE", {
                "run_id":run_id,"scope":"HOTEL","province":province,"city":city,"name":seed.get("name"),"tier":p.get("tier"),
                "candidate_key":candidate_key,"error_code":code,"error":str(exc),
                "retryable":code in {"PROVIDER_TIMEOUT","PROVIDER_DNS","PROVIDER_ERROR"},
                "operator_action_required":code not in {"PROVIDER_TIMEOUT","PROVIDER_DNS"},
            }, actor)
            return {"state":"FAILED", "code":code, "retryable":code in {"PROVIDER_TIMEOUT","PROVIDER_DNS","PROVIDER_ERROR"}}

    def _maybe_advance_tier(self, run_id: str, actor: str):
        events=_run_events(run_id)
        created=next(((e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_CREATED"),{})
        if created.get("mode") != "NATIONAL_TIERED":
            return
        advanced=[(e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_TIER_ADVANCED"]
        tier=int(advanced[-1].get("to_tier")) if advanced else int(created.get("tier") if created.get("tier") is not None else 5)
        if any(int(a.get("from_tier",-1))==tier for a in advanced):
            return
        if not _queue().tier_ready(run_id, tier):
            return
        # A tier is complete when every province discovery finished, every city discovery finished,
        # and every tier-matched hotel task has a terminal HOTEL_FINISHED event.
        prov_done={x.get("province") for x in [(e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_PROVINCE_FINISHED" and (e.evidence_json or {}).get("tier")==tier] if x.get("province")}
        prov_enq={x.get("province") for x in [(e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_PROVINCE_ENQUEUED" and (e.evidence_json or {}).get("tier")==tier] if x.get("province")}
        if prov_enq and prov_done != prov_enq:
            return
        cities={ (x.get("province"),x.get("city")) for x in [(e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_CITY_ENQUEUED" and (e.evidence_json or {}).get("tier")==tier] if x.get("city") }
        city_done={ (x.get("province"),x.get("city")) for x in [(e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_CITY_DISCOVERY_FINISHED" and (e.evidence_json or {}).get("tier")==tier] if x.get("city") }
        if cities and not cities.issubset(city_done):
            return
        hotel_enq={x.get("candidate_key") for x in [(e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_HOTEL_ENQUEUED" and (e.evidence_json or {}).get("tier")==tier] if x.get("candidate_key")}
        hotel_done={x.get("candidate_key") for x in [(e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_HOTEL_FINISHED" and (e.evidence_json or {}).get("tier")==tier] if x.get("candidate_key")}
        if hotel_enq and not hotel_enq.issubset(hotel_done):
            return
        idx=NATIONAL_TIER_SEQUENCE.index(tier) if tier in NATIONAL_TIER_SEQUENCE else len(NATIONAL_TIER_SEQUENCE)-1
        if idx >= len(NATIONAL_TIER_SEQUENCE)-1:
            event("REGIONAL_BUILD_TIERED_COMPLETED",{"run_id":run_id,"tier":tier,"state":"COMPLETED"},actor)
            return
        next_tier=NATIONAL_TIER_SEQUENCE[idx+1]
        if tier==5 and str(os.getenv("GO_HOTEL_TIER5_AUTO_ADVANCE") or "").lower() not in {"1","true","yes","on"}:
            event("REGIONAL_BUILD_TIER_PAUSED",{"run_id":run_id,"tier":5,"next_tier":4,"reason":"TIER5_ACCEPTANCE_REQUIRED"},actor)
            return
        enqueue({"run_id":run_id,"task":"ROOT","mode":"NATIONAL_TIERED","country":created.get("country") or "CN","province":None,"city":None,"actor":actor,"tier":next_tier},
                initial_events=(("REGIONAL_BUILD_TIER_ADVANCED", {"run_id":run_id,"from_tier":tier,"to_tier":next_tier,"to_tier_name":_tier_name(next_tier)}),))

    def advance_after_acceptance(self, run_id: str, actor: str, confirmation: str) -> dict:
        if confirmation != "TIER5_ACCEPTED_UNLOCK_TIER4":
            raise ValueError("TIER5_ACCEPTANCE_CONFIRMATION_REQUIRED")
        events=_run_events(run_id)
        created=next(((e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_CREATED"),{})
        if created.get("mode") != "NATIONAL_TIERED": raise ValueError("TIERED_BUILD_RUN_REQUIRED")
        paused=[e.evidence_json or {} for e in events if e.event_type=="REGIONAL_BUILD_TIER_PAUSED" and int((e.evidence_json or {}).get("tier") or 0)==5]
        if not paused: raise ValueError("TIER5_NOT_PAUSED_FOR_ACCEPTANCE")
        if any(e.event_type=="REGIONAL_BUILD_TIER_ADVANCED" and int((e.evidence_json or {}).get("from_tier") or 0)==5 for e in events):
            return {"run_id":run_id,"from_tier":5,"to_tier":4,"idempotent":True}
        enqueue({"run_id":run_id,"task":"ROOT","mode":"NATIONAL_TIERED","country":created.get("country") or "CN","province":None,"city":None,"actor":actor,"tier":4},
                initial_events=(("REGIONAL_BUILD_TIER_ACCEPTED", {"run_id":run_id,"tier":5,"actor":actor}),
                    ("REGIONAL_BUILD_TIER_ADVANCED", {"run_id":run_id,"from_tier":5,"to_tier":4,"to_tier_name":_tier_name(4),"acceptance_gate":True})))
        return {"run_id":run_id,"from_tier":5,"to_tier":4,"idempotent":False}

    def process_message(self, payload: dict):
        with SessionLocal() as s:
            catalog_scope.require_run(s,payload)
        task=payload.get("task")
        if task == "ROOT": return self._process_root(payload)
        elif task == "PROVINCE": return self._process_province(payload)
        elif task == "CITY": return self._process_city(payload)
        elif task == "HOTEL": return self._process_hotel(payload)
        else: raise ValueError("REGIONAL_BUILD_TASK_INVALID")

    def retry_failures(self, run_id: str, actor: str) -> dict:
        events=_run_events(run_id)
        created=next(((e.evidence_json or {}) for e in events if e.event_type=="REGIONAL_BUILD_CREATED"),{})
        run_mode=created.get("mode") or "REGION"; run_tier=created.get("tier"); target_name=created.get("target_name")
        failures=[]; failed_deliveries=set()
        for e in reversed(events):
            if e.event_type != "REGIONAL_BUILD_FAILURE": continue
            x=e.evidence_json or {}
            if not x.get("retryable"): continue
            if x.get("delivery_message_id") and not _queue().retry_needed(x["delivery_message_id"]): continue
            if x.get("delivery_message_id"):
                if x["delivery_message_id"] in failed_deliveries: continue
                failed_deliveries.add(x["delivery_message_id"])
            failures.append({**x, "retry_generation":e.hotel_auto_page_event_id})
        queued=0
        seen=set()
        for f in failures:
            key=(f.get("scope"),f.get("province"),f.get("city"),f.get("name"),f.get("delivery_message_id") if f.get("scope")=="DELIVERY" else None)
            if key in seen: continue
            seen.add(key)
            retry_tier=f.get("tier", run_tier)
            retry_generation=f["retry_generation"]
            if f.get("scope") == "DELIVERY":
                original=_queue().retry_payload(f["delivery_message_id"])
                enqueue({**original,"actor":actor,"retry_generation":retry_generation},supersedes=f["delivery_message_id"]); queued+=1
            elif f.get("scope") == "CITY":
                enqueue({"run_id":run_id,"task":"CITY","mode":run_mode,"country":"CN","province":f.get("province"),"city":f.get("city"),"actor":actor,"tier":retry_tier,"target_name":target_name,"retry_generation":retry_generation}, supersedes=f.get("delivery_message_id")); queued+=1
            elif f.get("scope") == "PROVINCE":
                enqueue({"run_id":run_id,"task":"PROVINCE","mode":run_mode,"country":"CN","province":f.get("province"),"actor":actor,"tier":retry_tier,"target_name":target_name,"retry_generation":retry_generation}, supersedes=f.get("delivery_message_id")); queued+=1
            elif f.get("scope") == "HOTEL":
                # Hotel-level failures are retried through the city task so provider discovery,
                # entity resolution and page synthesis are replayed idempotently from source truth.
                city=f.get("city"); province=f.get("province")
                city_key=("CITY_REPLAY",province,city)
                if city and city_key not in seen:
                    seen.add(city_key)
                    enqueue({"run_id":run_id,"task":"CITY","mode":run_mode,"country":"CN","province":province,"city":city,"actor":actor,"tier":retry_tier,"target_name":target_name,"retry_generation":retry_generation}, supersedes=f.get("delivery_message_id")); queued+=1
        event("REGIONAL_BUILD_RETRY_ENQUEUED", {"run_id":run_id,"queued":queued}, actor)
        return {"run_id":run_id,"queued":queued}

    def status(self, run_id: str | None = None) -> dict:
        with SessionLocal() as s:
            rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type.like("REGIONAL_BUILD_%")).order_by(HotelAutoPageEventRow.created_at.asc())).all()
            rows=catalog_scope.visible_events(s,rows)
        if run_id:
            rows=[r for r in rows if (r.evidence_json or {}).get("run_id") == run_id]
        run_ids=[]
        for r in rows:
            rid=(r.evidence_json or {}).get("run_id")
            if rid and rid not in run_ids: run_ids.append(rid)

        def unique_latest(items,keyfn):
            out={}
            for item in items:
                out[keyfn(item)]=item
            return list(out.values())

        runs=[]
        for rid in run_ids[-50:]:
            ev=[r for r in rows if (r.evidence_json or {}).get("run_id") == rid]
            created=next((r.evidence_json for r in ev if r.event_type=="REGIONAL_BUILD_CREATED"),{}) or {}
            province_tasks=len({(r.evidence_json or {}).get("province") for r in ev if r.event_type=="REGIONAL_BUILD_PROVINCE_ENQUEUED" and (r.evidence_json or {}).get("province")})
            city_keys={(x.get("province"),x.get("city")) for x in [(r.evidence_json or {}) for r in ev if r.event_type=="REGIONAL_BUILD_CITY_ENQUEUED"] if x.get("city")}
            city_tasks=len(city_keys)

            discovery_done=unique_latest(
                [r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_CITY_DISCOVERY_FINISHED"],
                lambda x:(x.get("province"),x.get("city"))
            )
            hotel_enqueued=unique_latest([r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_HOTEL_ENQUEUED"],
                lambda x:(x.get("tier"),x.get("province"),x.get("city"),x.get("candidate_key") or x.get("name")))
            hotel_finished=unique_latest(
                [r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_HOTEL_FINISHED"],
                lambda x:(x.get("tier"),x.get("province"),x.get("city"),x.get("candidate_key") or (x.get("name"),x.get("hotel_id")))
            )
            old_city_fin=[r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_CITY_FINISHED"]

            if discovery_done or hotel_enqueued or hotel_finished:
                discovered=sum(int(x.get("deduped") or x.get("discovered") or 0) for x in discovery_done)
                hotel_ids={x.get("hotel_id") for x in hotel_finished if x.get("hotel_id")}
                page_ids={x.get("hotel_id") for x in hotel_finished if x.get("hotel_id") and x.get("page") and x.get("state")=="COMPLETED" and (x.get("completeness_gate") or {}).get("passed")}
                conflicts=sum(1 for x in hotel_finished if int(x.get("conflicts") or 0)>0)
                failures=[r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_FAILURE"
                    and (not (r.evidence_json or {}).get("delivery_message_id") or _queue().retry_needed((r.evidence_json or {})["delivery_message_id"]))]
                actionable=[x for x in failures if x.get("operator_action_required")]
                queued_by_city={}
                finished_by_city={}
                for x in hotel_enqueued:
                    k=(x.get("province"),x.get("city")); queued_by_city[k]=queued_by_city.get(k,0)+1
                for x in hotel_finished:
                    k=(x.get("province"),x.get("city")); finished_by_city[k]=finished_by_city.get(k,0)+1
                discovery_keys={(x.get("province"),x.get("city")) for x in discovery_done}
                cities_finished=sum(1 for k in discovery_keys if finished_by_city.get(k,0)>=queued_by_city.get(k,0))
                needs_enrichment=sum(1 for x in hotel_finished if x.get("state")!="COMPLETED" or not (x.get("completeness_gate") or {}).get("passed"))
                failed_sources=sum(int(x.get("failures") or 0) for x in hotel_finished)
                if actionable or conflicts or failed_sources:
                    state="NEEDS_ATTENTION"
                elif needs_enrichment:
                    state="NEEDS_ENRICHMENT"
                elif city_tasks and cities_finished>=city_tasks:
                    state="COMPLETED"
                elif discovery_done or hotel_enqueued or any(r.event_type.endswith("_STARTED") for r in ev[-12:]):
                    state="RUNNING"
                else:
                    state="QUEUED"
                canonical=len(hotel_ids); pages=len(page_ids); failure_count=len(actionable)+failed_sources
                auto_recovering=max(0,len(failures)-len(actionable))
            else:
                city_fin=old_city_fin
                needs_enrichment=sum(int(x.get("canonical") or 0) for x in city_fin)
                fails=[r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_FAILURE"
                    and (not (r.evidence_json or {}).get("delivery_message_id") or _queue().retry_needed((r.evidence_json or {})["delivery_message_id"]))]
                conflicts=sum(int(x.get("conflicts") or 0) for x in city_fin)
                failure_count=len(fails)+sum(int(x.get("failures") or 0) for x in city_fin)
                discovered=sum(int(x.get("discovered") or 0) for x in city_fin)
                canonical=sum(int(x.get("canonical") or 0) for x in city_fin)
                pages=sum(int(x.get("pages") or 0) for x in city_fin)
                cities_finished=len(city_fin); auto_recovering=0
                if fails or conflicts: state="NEEDS_ATTENTION"
                elif needs_enrichment: state="NEEDS_ENRICHMENT"
                elif city_tasks and cities_finished>=city_tasks: state="COMPLETED"
                elif city_tasks: state="RUNNING"
                else: state="QUEUED"

            delivery=_queue().status(rid)
            if delivery['dead']:
                state='NEEDS_ATTENTION'
                failure_count=max(failure_count,delivery['dead'])
            elif delivery['queued'] or delivery['running']:
                if state == 'COMPLETED': state='RUNNING'
            runs.append({
                "run_id":rid,"mode":created.get("mode"),"country":created.get("country"),"province":created.get("province"),"city":created.get("city"),
                "delivery":delivery, "delivery_semantics":"AT_LEAST_ONCE",
                "province_tasks":province_tasks,"city_tasks":city_tasks,"cities_finished":cities_finished,
                "discovered":discovered,"canonical":canonical,"pages":pages,"conflicts":conflicts,
                "failures":failure_count,"needs_enrichment":needs_enrichment,"auto_recovering":auto_recovering,"state":state,
                "last_event_at":ev[-1].created_at.isoformat() if ev else None,
            })

        province_summary=[]
        latest_id=run_ids[-1] if run_ids else None
        if latest_id:
            latest=next((x for x in runs if x["run_id"]==latest_id),None)
            ev=[r for r in rows if (r.evidence_json or {}).get("run_id") == latest_id]
            provinces=[]
            for r in ev:
                x=r.evidence_json or {}; pr=x.get("province")
                if pr and pr not in provinces: provinces.append(pr)
            for pr in provinces:
                d=unique_latest([r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_CITY_DISCOVERY_FINISHED" and (r.evidence_json or {}).get("province")==pr], lambda x:(x.get("tier"),x.get("city")))
                hf=unique_latest([r.evidence_json or {} for r in ev if r.event_type=="REGIONAL_BUILD_HOTEL_FINISHED" and (r.evidence_json or {}).get("province")==pr], lambda x:(x.get("tier"),x.get("city"),x.get("candidate_key") or x.get("hotel_id")))
                ids={x.get("hotel_id") for x in hf if x.get("hotel_id")}
                page_ids={x.get("hotel_id") for x in hf if x.get("hotel_id") and x.get("page") and x.get("state")=="COMPLETED" and (x.get("completeness_gate") or {}).get("passed")}
                province_summary.append({
                    "province":pr,"cities_finished":len({x.get("city") for x in d if x.get("city")}),
                    "discovered":sum(int(x.get("deduped") or x.get("discovered") or 0) for x in d),
                    "canonical":len(ids),"pages":len(page_ids),
                    "conflicts":sum(1 for x in hf if int(x.get("conflicts") or 0)>0),
                    "failures":sum(1 for r in ev if r.event_type=="REGIONAL_BUILD_FAILURE" and (r.evidence_json or {}).get("province")==pr and (r.evidence_json or {}).get("operator_action_required")),
                })
        return {"runs":list(reversed(runs)),"province_summary":province_summary,"provider_count":len(_providers()),"provider":_provider_summary(),"queue_topic":TOPIC}

    def exceptions(self, limit: int = 200) -> dict:
        with SessionLocal() as s:
            rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type.in_(["REGIONAL_BUILD_FAILURE","REGIONAL_BUILD_CONFLICT"]),catalog_scope.event_filter(s)).order_by(HotelAutoPageEventRow.created_at.desc()).limit(max(20,min(limit*5,2000)))).all()
            rows=catalog_scope.visible_events(s,rows)
        grouped={}
        for r in rows:
            x=r.evidence_json or {}
            fingerprint=(
                r.event_type,x.get("run_id"),x.get("scope"),x.get("province"),x.get("city"),
                x.get("hotel_id") or x.get("candidate_key") or x.get("name"),x.get("error_code") or x.get("error")
            )
            if fingerprint in grouped:
                grouped[fingerprint]["occurrences"] += 1
                continue
            resolved=bool(x.get("delivery_message_id")) and not _queue().retry_needed(x["delivery_message_id"])
            auto_retry=bool(x.get("retryable")) and not bool(x.get("operator_action_required")) and not resolved
            grouped[fingerprint]={
                "type":r.event_type,"created_at":r.created_at.isoformat(),"occurrences":1,
                "severity":"RECOVERY_TRACKED" if resolved else ("ACTION_REQUIRED" if (r.event_type=="REGIONAL_BUILD_CONFLICT" or x.get("operator_action_required")) else "AUTO_RECOVERABLE"),
                "auto_retryable":auto_retry,**x,"delivery_resolved_or_recovering":resolved,
            }
        items=list(grouped.values())[:max(1,min(limit,1000))]
        return {
            "items":items,
            "action_required":sum(1 for x in items if x.get("severity")=="ACTION_REQUIRED"),
            "auto_recoverable":sum(1 for x in items if x.get("severity")=="AUTO_RECOVERABLE"),
        }


regional_hotel_build_service=RegionalHotelBuildService()

