from __future__ import annotations
import json, os, pathlib, sys
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'staging'/'bringup'/'infra.local.json'

def pg_check(url):
    try:
        import psycopg
        raw=url.replace('postgresql+psycopg://','postgresql://',1)
        with psycopg.connect(raw,connect_timeout=8) as c:
            with c.cursor() as cur:
                cur.execute('show server_version_num'); version=int(cur.fetchone()[0])
                cur.execute('select current_database(), current_user'); db,user=cur.fetchone()
        return {'status':'PASS' if version>=160000 else 'FAIL','server_version_num':version,'database':db,'user':user}
    except Exception as e: return {'status':'BLOCKED','error':type(e).__name__+': '+str(e)[:300]}

def redis_check(url):
    try:
        import redis
        r=redis.Redis.from_url(url,socket_connect_timeout=8,socket_timeout=8)
        pong=r.ping(); info=r.info('server');
        return {'status':'PASS' if pong else 'FAIL','redis_version':info.get('redis_version')}
    except Exception as e: return {'status':'BLOCKED','error':type(e).__name__+': '+str(e)[:300]}

def main():
    pg=os.getenv('STAGING_DATABASE_URL','').strip(); rd=os.getenv('STAGING_REDIS_URL','').strip()
    data={'generated_at':datetime.now(timezone.utc).isoformat(),
          'PG16':pg_check(pg) if pg else {'status':'BLOCKED','error':'STAGING_DATABASE_URL missing'},
          'REDIS':redis_check(rd) if rd else {'status':'BLOCKED','error':'STAGING_REDIS_URL missing'}}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps(data,indent=2)); return 0 if all(data[k]['status']=='PASS' for k in ('PG16','REDIS')) else 2
if __name__=='__main__': sys.exit(main())
