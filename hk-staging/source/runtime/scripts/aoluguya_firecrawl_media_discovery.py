#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
import httpx
from go_hotel.services.media_harvester import classify_scene

DEFAULT_ENDPOINT='https://api.firecrawl.dev/v2/search'
TARGET_CANDIDATE_CAPACITY=160
SCENE_BUDGETS={
    'EXTERIOR':12, 'LOBBY':12, 'ROOM':30, 'DINING':18,
    'WELLNESS':12, 'SIGNATURE_SPACE':16,
}
DEFAULT_QUERIES=[
    '敖麓谷雅 AOLUGUYA 酒店 图片 房型 大堂 餐厅 泳池 SPA 宴会厅',
    'AOLUGUYA hotel exterior lobby rooms restaurant pool spa banquet',
    'site:hyatt.com AOLUGUYA hotel rooms lobby restaurant pool spa',
    'site:ctrip.com 敖麓谷雅 酒店 房型 图片',
    'site:trip.com AOLUGUYA Hotel Harbin rooms images',
    'site:agoda.com AOLUGUYA Hotel Harbin images',
    'site:booking.com AOLUGUYA Hotel Harbin images',
    '敖麓谷雅 酒店 外观 大堂',
    '敖麓谷雅 酒店 客房 套房 卫生间',
    '敖麓谷雅 酒店 餐厅 早餐 中餐厅 牛排馆',
    '敖麓谷雅 酒店 泳池 健身 SPA',
    '敖麓谷雅 酒店 宴会厅 会议室 鄂温克 驯鹿',
]

def select_to_scene_budgets(items: list[dict], target_total: int, scene_budgets: dict[str,int]) -> tuple[list[dict],dict]:
    buckets={scene:[] for scene in scene_budgets}
    overflow=[]
    for item in items:
        scene=classify_scene(title=item.get('title'),alt=item.get('alt'),context=item.get('context'),source_url=item.get('source_url'))
        item={**item,'discovered_scene':scene}
        (buckets[scene] if scene in buckets else overflow).append(item)
    selected=[]; selected_ids=set()
    for scene,budget in scene_budgets.items():
        for item in buckets[scene][:budget]:
            selected.append(item); selected_ids.add((item['source_url'],item['source_group']))
    for item in items:
        key=(item['source_url'],item['source_group'])
        if len(selected)>=target_total: break
        if key not in selected_ids:
            selected.append(item); selected_ids.add(key)
    selected=selected[:target_total]
    counts=Counter(x.get('discovered_scene') or classify_scene(title=x.get('title'),alt=x.get('alt'),context=x.get('context'),source_url=x.get('source_url')) for x in selected)
    gates={scene:counts.get(scene,0)>=budget for scene,budget in scene_budgets.items()}
    return selected,{'scene_counts':dict(counts),'scene_budget_checks':gates,'scene_budget_gate_pass':all(gates.values())}

def group_for(page_url: str|None, image_url: str|None) -> str:
    host=(urlparse(page_url or image_url or '').hostname or '').lower()
    if 'hyatt.com' in host or 'aoluguya' in host: return 'HOTEL_OFFICIAL'
    if 'ctrip.com' in host: return 'CTRIP'
    if host.endswith('trip.com') or '.trip.com' in host: return 'TRIPCOM'
    if 'agoda.com' in host: return 'AGODA'
    if 'booking.com' in host: return 'BOOKING'
    return host.upper() or 'UNKNOWN'

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',required=True)
    ap.add_argument('--evidence-out',required=True)
    ap.add_argument('--endpoint',default=DEFAULT_ENDPOINT)
    ap.add_argument('--limit',type=int,default=20)
    ap.add_argument('--target-total',type=int,default=TARGET_CANDIDATE_CAPACITY)
    args=ap.parse_args()
    key=(os.getenv('GO_FIRECRAWL_API_KEY') or '').strip()
    if not key:
        print('FIRECRAWL_API_KEY_REQUIRED',file=sys.stderr); return 2
    if not args.endpoint.startswith('https://'):
        print('FIRECRAWL_HTTPS_REQUIRED',file=sys.stderr); return 2
    headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'}
    items=[]; failures=[]; raw_counts=[]
    seen=set()
    with httpx.Client(timeout=70.0,follow_redirects=True) as client:
        for q in DEFAULT_QUERIES:
            payload={'query':q,'limit':max(3,min(args.limit,20)),'sources':['web','images'],'country':'CN','safe':True,'timeout':60000,'ignoreInvalidURLs':True,'scrapeOptions':{'formats':['markdown']}}
            try:
                r=client.post(args.endpoint,json=payload,headers=headers)
                if r.status_code>=400:
                    failures.append({'query':q,'error':f'HTTP_{r.status_code}'}); continue
                obj=r.json()
                data=obj.get('data') if isinstance(obj,dict) and isinstance(obj.get('data'),dict) else {}
                images=data.get('images') if isinstance(data.get('images'),list) else []
                raw_counts.append({'query':q,'image_count':len(images)})
                for img in images:
                    if not isinstance(img,dict): continue
                    u=str(img.get('imageUrl') or img.get('url') or '').strip()
                    if not u.startswith(('http://','https://')): continue
                    page=str(img.get('sourceUrl') or img.get('sourceURL') or img.get('source_url') or '').strip() or None
                    title=str(img.get('title') or img.get('alt') or img.get('imageDescription') or '').strip() or None
                    context=str(img.get('description') or img.get('imageDescription') or img.get('sourceTitle') or '').strip() or None
                    # Same image URL from different source pages is kept once per source group.
                    grp=group_for(page,u)
                    dedupe=(u,grp)
                    if dedupe in seen: continue
                    seen.add(dedupe)
                    items.append({'source_url':u,'source_page_url':page,'source_group':grp,'source_type':'PUBLIC_WEB','role':'GALLERY','title':title,'alt':title,'context':context})
            except Exception as exc:
                failures.append({'query':q,'error':type(exc).__name__})
    target_total=max(30,min(args.target_total,TARGET_CANDIDATE_CAPACITY))
    items,selection=select_to_scene_budgets(items,target_total,SCENE_BUDGETS)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    payload={'hotel_id':'hotel_aoluguya','hotel_name':'敖麓谷雅','policy_version':'MEDIA_DISCOVERY_2.0.2','target_candidate_capacity':target_total,'scene_budgets':SCENE_BUDGETS,'items':items}
    Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    scenes=Counter(classify_scene(title=x.get('title'),alt=x.get('alt'),context=x.get('context'),source_url=x.get('source_url')) for x in items)
    groups=Counter(x['source_group'] for x in items)
    evidence={'evidence_type':'AOLUGUYA_FIRECRAWL_MEDIA_DISCOVERY_V2_0_2','query_count':len(DEFAULT_QUERIES),'per_query_limit':max(3,min(args.limit,20)),'target_candidate_capacity':target_total,'candidate_count':len(items),'capacity_gate_pass':len(items)>=target_total,'scene_budgets':SCENE_BUDGETS,**selection,'source_groups':dict(groups),'scene_candidates':dict(scenes),'query_image_counts':raw_counts,'failures':failures,'secret_persisted':False}
    ev=json.dumps(evidence,ensure_ascii=False,indent=2,sort_keys=True).encode()
    Path(args.evidence_out).parent.mkdir(parents=True,exist_ok=True); Path(args.evidence_out).write_bytes(ev)
    print(json.dumps({'candidate_count':len(items),'source_groups':dict(groups),'scene_candidates':dict(scenes),'evidence_sha256':hashlib.sha256(ev).hexdigest()},ensure_ascii=False))
    return 0 if evidence['capacity_gate_pass'] and evidence['scene_budget_gate_pass'] else 2
if __name__=='__main__': sys.exit(main())
