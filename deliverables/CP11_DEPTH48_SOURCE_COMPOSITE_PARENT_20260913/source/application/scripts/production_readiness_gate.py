#!/usr/bin/env python3
import json, os, sys
checks=[]
def add(key,ok,blocker,detail): checks.append({"key":key,"passed":bool(ok),"blocker":blocker,"detail":detail})
env=os.getenv("APP_ENV","local")
add("jwt_key_not_default",os.getenv("JWT_SIGNING_KEY","") not in ("","dev-only-change-me-jwt"),True,"Set a non-default JWT key")
add("vault_key_not_default",os.getenv("CONNECTOR_VAULT_MASTER_KEY","") not in ("","dev-only-change-me"),True,"Set a non-default vault key")
add("secure_cookie",env!="production" or os.getenv("COOKIE_SECURE","false").lower()=="true",True,"Secure cookies required in production")
add("admin_mfa",env!="production" or os.getenv("MFA_REQUIRED_FOR_ADMIN","false").lower()=="true",True,"Admin MFA required in production")
add("postgres_url",env!="production" or os.getenv("DATABASE_URL","").startswith("postgresql+psycopg://"),True,"Production must use PostgreSQL")
blockers=sum(1 for x in checks if x['blocker'] and not x['passed'])
result={"environment":env,"status":"PASS" if blockers==0 else "BLOCKED","blocker_count":blockers,"checks":checks}
print(json.dumps(result,indent=2))
sys.exit(0 if blockers==0 else 2)
