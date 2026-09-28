"""Isolated subprocess actor used by the C07 durability/concurrency acceptance."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from sqlalchemy import select
from go_hotel.db.models import (Base, TravelerProfileRow, ProfileConsentRow, ProfileFactRow,
    ProfileAccessAuditRow, ProfileTravelerPermissionRow)
from go_hotel.db.session import SessionLocal, engine
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault
from go_hotel.travel_intelligence.service import travel_intelligence_service as service
from go_hotel.travel_intelligence import preferences as implementation


def emit(kind, **data):
    print(json.dumps({"kind":kind, "pid":os.getpid(), "at":datetime.now(timezone.utc).isoformat(),
        "monotonic_ns":time.monotonic_ns(), **data}), flush=True)


def gate(config, name):
    if config.get("pause") != name:
        return
    Path(config["ready"]).write_text(name)
    emit("paused", point=name)
    deadline=time.monotonic()+20
    while not Path(config["release"]).exists():
        if time.monotonic()>deadline:
            raise RuntimeError("ISOLATED_PROCESS_GATE_TIMEOUT")
        time.sleep(0.01)
    emit("resumed", point=name)


def committed_marker(config):
    """Publish only after revoke_consent returned from its committed transaction."""
    if not config.get("committed_marker"):
        return
    marker=Path(config["committed_marker"])
    temporary=marker.with_suffix(marker.suffix+".tmp")
    event={"event":"CONSENT_WITHDRAWAL_COMMIT_ACK","pid":os.getpid(),
        "at":datetime.now(timezone.utc).isoformat(),"monotonic_ns":time.monotonic_ns()}
    with temporary.open("w") as handle:
        json.dump(event,handle);handle.write("\n");handle.flush();os.fsync(handle.fileno())
    os.replace(temporary,marker)
    emit("commit_ack_published",marker=marker.name)


config=json.load(sys.stdin)
source=Path(implementation.__file__)
emit("started", operation=config["operation"], source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
if config.get("started_marker"):
    Path(config["started_marker"]).write_text(str(os.getpid()))

if config.get("pause")=="after_consent":
    original=implementation._active_consents
    def active(*args, **kwargs):
        result=original(*args, **kwargs)
        gate(config,"after_consent")
        return result
    implementation._active_consents=active
elif config.get("pause")=="before_commit":
    original=implementation._audit
    def audit(*args, **kwargs):
        result=original(*args, **kwargs)
        gate(config,"before_commit")
        return result
    implementation._audit=audit

try:
    gate(config,"before_operation")
    operation=config["operation"]
    if operation=="setup":
        Base.metadata.create_all(engine, tables=[r.__table__ for r in
            (TravelerProfileRow,ProfileConsentRow,ProfileFactRow,ProfileAccessAuditRow,ProfileTravelerPermissionRow)])
        t=datetime.now(timezone.utc)
        with SessionLocal.begin() as s:
            s.add(TravelerProfileRow(traveler_id="process-traveler",user_id="process-owner",
                full_name="C07 SYNTHETIC PROCESS",relationship_type="SELF",status="ACTIVE",created_at=t,updated_at=t))
        # Graph visibility is a second, narrower release grant layered over
        # the explicit preference grant. Keep the same exact purpose so process
        # durability is tested without weakening cross-journey isolation.
        vault.grant_consent("process-owner",{"traveler_id":"process-traveler",
            "consent_type":"TRAVELER_CONTEXT","purpose":"HOTEL_PLANNING",
            "scope":["TRAVEL_PREFERENCES"],"expires_at":(t+timedelta(days=1)).isoformat()})
        result=vault.grant_consent("process-owner",{"traveler_id":"process-traveler",
            "consent_type":"EXPLICIT_TRAVEL_PREFERENCE","purpose":"HOTEL_PLANNING",
            "scope":["TRAVEL_PREFERENCE:HOTEL_ROOM"],"expires_at":(t+timedelta(days=1)).isoformat()})
    elif operation in {"save","save_exit"}:
        result=service.save_preference("process-owner","process-traveler",preference_key="HOTEL_ROOM",
            value={"quiet":config.get("quiet",True)},purpose="HOTEL_PLANNING",consent_id=config["consent_id"],
            confirmed=True,expected_preference_id=config.get("expected_preference_id"))
    elif operation=="read":
        result=service.preferences("process-traveler",purpose="HOTEL_PLANNING",actor_id="isolated-acceptance")
        result["graph_preferences"]=service.traveler_graph("process-traveler",purpose="HOTEL_PLANNING")["durable_preferences"]
    elif operation=="revoke_consent":
        result=vault.revoke_consent("process-owner",config["consent_id"])
        committed_marker(config)
    elif operation=="revoke_preference":
        result=service.revoke_preference("process-owner","process-traveler",config["preference_id"])
    elif operation=="inspect":
        with SessionLocal() as s:
            result={"consents":[{"id":r.consent_id,"status":r.status} for r in s.scalars(select(ProfileConsentRow))],
                "facts":[{"id":r.fact_id,"status":r.status,"superseded_by":r.superseded_by} for r in s.scalars(select(ProfileFactRow))]}
    else:
        raise RuntimeError("UNKNOWN_ISOLATED_OPERATION")
    emit("result", result=result)
    if operation=="save_exit":
        os._exit(73)  # Intentional abrupt exit after the service committed.
except ValueError as exc:
    emit("result", error=str(exc))
finally:
    engine.dispose()
