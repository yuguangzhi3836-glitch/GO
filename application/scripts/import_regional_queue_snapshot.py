#!/usr/bin/env python3
"""Validate a stopped Redis queue's JSON export; apply idempotently to the SQL queue.

Export format: JSON array of the raw strings returned by LRANGE go:queue:hotel-regional-build 0 -1,
or an array of those decoded JSON objects. No Redis item is removed by this script.
Stop old workers before export. Preserve the export and receipt until verification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from go_hotel.autonomy.durable import canonical, digest
from go_hotel.services.regional_hotel_build import enqueue, TOPIC


def validate(raw):
    if len(raw) > 50 * 1024 * 1024:
        raise ValueError('REGIONAL_SNAPSHOT_TOO_LARGE')
    records=json.loads(raw)
    if not isinstance(records,list):raise ValueError('REGIONAL_SNAPSHOT_LIST_REQUIRED')
    out=[]; seen={}; identity={}
    for record in records:
        if isinstance(record,str):record=json.loads(record)
        if not isinstance(record,dict) or record.get('topic')!=TOPIC or not isinstance(record.get('message_id'),str):
            raise ValueError('REGIONAL_SNAPSHOT_MESSAGE_INVALID')
        payload=record.get('payload')
        if not isinstance(payload,dict) or not payload.get('run_id') or payload.get('task') not in {'ROOT','PROVINCE','CITY','HOTEL'}:
            raise ValueError('REGIONAL_SNAPSHOT_PAYLOAD_INVALID')
        ph=digest(payload)
        mid=record['message_id']
        key=digest({k:payload.get(k) for k in ('run_id','task','tier','province','city','candidate_key','retry_generation')})
        if (mid in seen and seen[mid]!=ph) or (key in identity and identity[key]!=ph):
            raise ValueError('REGIONAL_SNAPSHOT_IDENTITY_CONFLICT')
        if mid not in seen:out.append(record)
        seen[mid]=ph;identity[key]=ph
    return out


def import_snapshot(raw, *, apply=False, submit=enqueue):
    records=validate(raw) # All identities validate before the first write.
    receipt={'snapshot_sha256':hashlib.sha256(raw).hexdigest(),'validated_messages':len(records),
             'applied':apply,'redis_items_deleted':0,'messages':[]}
    if apply:
        for item in records:
            mid=submit(item['payload'])
            receipt['messages'].append({'legacy_message_id':item['message_id'],'durable_message_id':mid})
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args()
    if args.receipt.exists():parser.error('Receipt path must be new; keep prior evidence')
    result=import_snapshot(args.snapshot.read_bytes(),apply=args.apply)
    args.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='messages'},ensure_ascii=False))


if __name__=='__main__':main()
