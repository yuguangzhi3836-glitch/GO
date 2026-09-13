#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from urllib.parse import urlparse
from go_hotel.services.media_harvester import MediaHarvesterService

HOTEL_ID='hotel_aoluguya'

def source_group(c: dict) -> str:
    if c.get('source_group'): return str(c['source_group']).upper()
    u=str(c.get('source_page_url') or c.get('source_url') or '')
    host=(urlparse(u).hostname or '').lower()
    if 'hyatt.com' in host or 'aoluguya' in host: return 'HOTEL_OFFICIAL'
    if 'ctrip.com' in host: return 'CTRIP'
    if 'trip.com' in host: return 'TRIPCOM'
    if 'booking.com' in host: return 'BOOKING'
    if 'agoda.com' in host: return 'AGODA'
    return host.upper() or 'UNKNOWN'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--candidates',required=True)
    ap.add_argument('--cache-dir',required=True)
    ap.add_argument('--evidence-out',required=True)
    ap.add_argument('--rights-owner',default='AOLUGUYA Hotel')
    ap.add_argument('--owner-verified',action='store_true')
    args=ap.parse_args()
    raw=json.loads(Path(args.candidates).read_text(encoding='utf-8'))
    candidates=raw.get('items') if isinstance(raw,dict) else raw
    if not isinstance(candidates,list): raise SystemExit('CANDIDATE_LIST_REQUIRED')
    svc=MediaHarvesterService(args.cache_dir)
    prepared=[]
    for c in candidates:
        if not isinstance(c,dict) or not str(c.get('source_url') or '').startswith(('http://','https://')): continue
        x={k:v for k,v in c.items() if k in {'source_url','hotel_id','role','room_type_id','source_type','source_group','observed_at','request_headers','timeout_seconds','title','alt','context'}}
        x['hotel_id']=HOTEL_ID
        x.setdefault('role','GALLERY')
        x.setdefault('source_type','PUBLIC_WEB')
        x['source_group']=source_group(c)
        prepared.append(x)
    harvested=svc.harvest_batch(prepared)
    # Media Discovery 2.0.2: the publishable inference is based on the same
    # image bytes/visual appearing across two independent source groups. It is
    # intentionally separate from owner attestation and ignores page-level UI.
    # A content mark must be attached to the harvested record by byte inspection
    # and remains an unconditional blocker inside the policy service.
    rights=svc.promote_multi_source_hotel_origin(
        HOTEL_ID, rights_owner=args.rights_owner, rights_regions=['GLOBAL'],
        min_source_groups=2, max_phash_distance=10,
    )
    owner_rights=None
    if args.owner_verified:
        owner_rights=svc.promote_owned_hotel_assets(
            HOTEL_ID, rights_owner=args.rights_owner, owner_verified=True, rights_regions=['GLOBAL'],
            allowed_source_groups={'HOTEL_OFFICIAL','CTRIP','TRIPCOM','BOOKING','AGODA'},
            evidence_reference='go://hotel-media/owner-attestation/hotel_aoluguya/2026-09-04',
        )
    gate=svc.six_scene_coverage(HOTEL_ID)
    evidence={
      'evidence_type':'AOLUGUYA_REAL_IMAGE_BYTE_HARVEST_GATE_V2_0_2',
      'rights_policy_version':'MEDIA_DISCOVERY_2.0.2',
      'platform_page_ui_is_not_content_mark':True,
      'candidate_count':len(prepared),
      'downloaded_count':harvested['downloaded_count'],
      'failure_count':harvested['failure_count'],
      'failures':harvested['failures'],
      'multi_source_rights':rights,
      'owner_verified_rights':owner_rights,
      'golden_media_gate':gate,
      'result':'PASS' if gate['golden_media_gate_pass'] else 'HOLD',
    }
    payload=json.dumps(evidence,ensure_ascii=False,indent=2,sort_keys=True).encode()
    out=Path(args.evidence_out); out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(payload)
    print(json.dumps({'result':evidence['result'],'downloaded':evidence['downloaded_count'],'publishable_unique':gate['unique_publishable_media'],'six_scene_complete':gate['six_scene_complete'],'evidence_sha256':hashlib.sha256(payload).hexdigest()},ensure_ascii=False))
    return 0 if evidence['result']=='PASS' else 2

if __name__=='__main__': sys.exit(main())
