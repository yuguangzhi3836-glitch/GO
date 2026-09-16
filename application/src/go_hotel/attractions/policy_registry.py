"""Synthetic/internal attraction policy contract.

This module validates and evaluates supplier-shaped fixtures.  It does not
authenticate a supplier or establish production provenance.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STATES={"ACTIVE","EXPIRED","WITHDRAWN"}
DECISIONS={"ELIGIBLE","TOO_EARLY","TOO_LATE","EXPIRED","WITHDRAWN","LEGACY_UNVERIFIED"}
REQUIRED={"supplier_id","product_id","go_offer_id","version","state","destination_timezone",
          "effective_from","opens_minutes_before_session","closes_minutes_after_session",
          "allow_open_ended","amendment_allowed","cancellation_allowed","raw_payload_ref",
          "raw_payload_sha256","source_uri","observed_at"}
ERR="ATTRACTION_POLICY_"

def _dt(value,name):
    if not isinstance(value,str): raise ValueError(ERR+name+"_INVALID")
    try: out=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError: raise ValueError(ERR+name+"_INVALID")
    if out.tzinfo is None: raise ValueError(ERR+name+"_TZ_REQUIRED")
    return out

def _version(value):
    if not isinstance(value,str) or not value or any(not x.isdigit() for x in value.split(".")):
        raise ValueError(ERR+"VERSION_INVALID")
    return tuple(int(x) for x in value.split("."))

def _canonical_hash(policy):
    body={k:v for k,v in policy.items() if k!="payload_sha256"}
    return sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def validate(policy):
    if not isinstance(policy,dict) or REQUIRED-policy.keys(): raise ValueError(ERR+"SCHEMA_INVALID")
    if policy["state"] not in STATES: raise ValueError(ERR+"STATE_INVALID")
    for key in ("supplier_id","product_id","go_offer_id","raw_payload_ref","source_uri"):
        if not isinstance(policy[key],str) or not policy[key].strip(): raise ValueError(ERR+key.upper()+"_INVALID")
    _version(policy["version"])
    try: ZoneInfo(policy["destination_timezone"])
    except (ZoneInfoNotFoundError,TypeError): raise ValueError(ERR+"TIMEZONE_INVALID")
    start=_dt(policy["effective_from"],"EFFECTIVE_FROM")
    end=_dt(policy["effective_until"],"EFFECTIVE_UNTIL") if policy.get("effective_until") else None
    if end is None and policy["allow_open_ended"] is not True: raise ValueError(ERR+"OPEN_ENDED_NOT_ALLOWED")
    if end and end<=start: raise ValueError(ERR+"EFFECTIVE_RANGE_INVALID")
    for key,lo,hi in (("opens_minutes_before_session",0,10080),("closes_minutes_after_session",0,10080)):
        value=policy[key]
        if type(value) is not int or not lo<=value<=hi: raise ValueError(ERR+key.upper()+"_INVALID")
    for key in ("allow_open_ended","amendment_allowed","cancellation_allowed"):
        if type(policy[key]) is not bool: raise ValueError(ERR+key.upper()+"_INVALID")
    if not isinstance(policy["raw_payload_sha256"],str) or len(policy["raw_payload_sha256"])!=64:
        raise ValueError(ERR+"RAW_HASH_INVALID")
    int(policy["raw_payload_sha256"],16)
    _dt(policy["observed_at"],"OBSERVED_AT")
    if policy.get("supersedes") is not None: _version(policy["supersedes"])
    result=deepcopy(policy); result["payload_sha256"]=_canonical_hash(result)
    return result

class Registry:
    def __init__(self): self._policies={}; self.audit=[]

    def import_bound_batch(self, entries):
        """Import only policies whose claimed digest matches supplied raw bytes.

        This proves local byte binding, not supplier identity or authorization.
        Every digest is checked before registry mutation, so one mismatch rejects
        the entire batch without partial policy or audit writes.
        """
        policies = []
        if not isinstance(entries, (list, tuple)):
            raise ValueError(ERR+"RAW_BATCH_INVALID")
        for entry in entries:
            if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                    or not isinstance(entry[0], dict)
                    or type(entry[1]) is not bytes):
                raise ValueError(ERR+"RAW_PAYLOAD_BYTES_REQUIRED")
            policy, raw_payload = entry
            claimed = policy.get("raw_payload_sha256")
            actual = sha256(raw_payload).hexdigest()
            if claimed != actual:
                raise ValueError(ERR+"RAW_HASH_MISMATCH")
            policies.append(policy)
        return self.import_batch(policies)

    @staticmethod
    def _key(p): return p["supplier_id"],p["product_id"],p["go_offer_id"]
    def import_batch(self, policies):
        checked=[validate(p) for p in policies]
        if len({(self._key(p),p["version"]) for p in checked})!=len(checked):
            raise ValueError(ERR+"BATCH_DUPLICATE")
        staged=deepcopy(self._policies); events=[]
        for p in checked:
            key=self._key(p); versions=staged.setdefault(key,{})
            old=versions.get(p["version"])
            if old:
                if old["payload_sha256"]!=p["payload_sha256"]: raise ValueError(ERR+"VERSION_HASH_CONFLICT")
                events.append(("IDEMPOTENT_REPLAY",key,p["version"])); continue
            current=max(versions.values(),key=lambda x:_version(x["version"])) if versions else None
            if current and _version(p["version"])<_version(current["version"]):
                raise ValueError(ERR+"STALE_VERSION")
            if current and p.get("supersedes")!=current["version"]:
                raise ValueError(ERR+"SUPERSEDES_MISMATCH")
            versions[p["version"]]=p; events.append(("ACCEPTED",key,p["version"]))
        self._policies=staged
        self.audit.extend({"reason":r,"key":k,"version":v} for r,k,v in events)
        return [r for r,_,_ in events]
    def current(self,supplier_id,product_id,go_offer_id):
        versions=self._policies.get((supplier_id,product_id,go_offer_id))
        if not versions: return None
        return max(versions.values(),key=lambda x:_version(x["version"]))
    def decide(self,supplier_id,product_id,go_offer_id,session_time,at_time):
        p=self.current(supplier_id,product_id,go_offer_id)
        if not p: return {"decision":"LEGACY_UNVERIFIED","reason":"POLICY_UNKNOWN"}
        now=_dt(at_time,"AT_TIME"); session=_dt(session_time,"SESSION_TIME")
        zone=ZoneInfo(p["destination_timezone"]); now=now.astimezone(zone); session=session.astimezone(zone)
        if p["state"]=="WITHDRAWN": result=("WITHDRAWN","POLICY_WITHDRAWN")
        elif p["state"]=="EXPIRED": result=("EXPIRED","POLICY_STATE_EXPIRED")
        elif now<_dt(p["effective_from"],"EFFECTIVE_FROM").astimezone(zone): result=("LEGACY_UNVERIFIED","POLICY_NOT_EFFECTIVE")
        elif p.get("effective_until") and now>_dt(p["effective_until"],"EFFECTIVE_UNTIL").astimezone(zone): result=("EXPIRED","POLICY_TIME_EXPIRED")
        elif now<session-timedelta(minutes=p["opens_minutes_before_session"]): result=("TOO_EARLY","WINDOW_NOT_OPEN")
        elif now>session+timedelta(minutes=p["closes_minutes_after_session"]): result=("TOO_LATE","WINDOW_CLOSED")
        else: result=("ELIGIBLE","IN_REDEMPTION_WINDOW")
        self.audit.append({"reason":result[1],"key":self._key(p),"version":p["version"]})
        return {"decision":result[0],"reason":result[1],"policy_version":p["version"],
                "amendment_allowed":p["amendment_allowed"],"cancellation_allowed":p["cancellation_allowed"],
                "synthetic_only":True}
