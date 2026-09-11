from __future__ import annotations
import argparse
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument('--source',required=True,type=Path); a=p.parse_args()
    path=a.source/'src/go_hotel/db/models.py'
    text=path.read_text()
    marker='ck_payment_deadline_vertical'
    idx=text.find(marker)
    if idx<0: raise SystemExit('PAYMENT_DEADLINE_SCHEMA_CONSTRAINT_NOT_FOUND')
    lo=max(0,idx-600); hi=min(len(text),idx+250); block=text[lo:hi]
    variants=[
        ("'RAIL','ATTRACTION'", "'RAIL','ATTRACTION','RIDE','RENTAL'"),
        ("'RAIL', 'ATTRACTION'", "'RAIL', 'ATTRACTION', 'RIDE', 'RENTAL'"),
        ('"RAIL","ATTRACTION"', '"RAIL","ATTRACTION","RIDE","RENTAL"'),
        ('"RAIL", "ATTRACTION"', '"RAIL", "ATTRACTION", "RIDE", "RENTAL"'),
    ]
    for old,new in variants:
        if old in block:
            block=block.replace(old,new,1)
            text=text[:lo]+block+text[hi:]
            path.write_text(text)
            print('DEPTH39_PAYMENT_DEADLINE_SCHEMA=RIDE_RENTAL_ENABLED')
            return
    raise SystemExit('PAYMENT_DEADLINE_SCHEMA_ENUM_PATTERN_NOT_FOUND:'+block.replace('\n',' ')[:500])

if __name__=='__main__': main()
