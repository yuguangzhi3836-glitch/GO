"""Exercise a real disposable HTTP server, never a browser or Hong Kong target."""
from __future__ import annotations
import argparse
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--fingerprint',type=Path,required=True)
    p.add_argument('--expected-tree',required=True)
    p.add_argument('--evidence',type=Path,required=True)
    args=p.parse_args()
    evidence=args.evidence.absolute(); evidence.mkdir(exist_ok=True)
    source=args.source.absolute(); fingerprint=args.fingerprint.absolute()
    fp=json.loads(fingerprint.read_text())
    checks=[]; records=[]
    def check(name, result):
        checks.append({'name':name,'passed':bool(result)})
        if not result: raise AssertionError(name)

    class EntryParser(HTMLParser):
        def __init__(self): super().__init__(); self.refs=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='script' and a.get('src'): self.refs.append(a['src'])
            if tag=='link' and a.get('rel')=='stylesheet' and a.get('href'): self.refs.append(a['href'])

    with tempfile.TemporaryDirectory(prefix='go-depth36-http-') as temporary:
        parent=Path(temporary); state=parent/'state'; logfile=parent/'server.log'
        with socket.socket() as s: s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        cmd=[sys.executable,'-B',str(source/'scripts/acceptance_runtime.py'),'--source',str(source),
            '--fingerprint',str(fingerprint),'--expected-tree',args.expected_tree,'--state',str(state),'--port',str(port)]
        log=logfile.open('wb')
        child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env={
            'PATH':os.environ.get('PATH','/usr/bin:/bin'),'PYTHONDONTWRITEBYTECODE':'1',
            'DATABASE_URL':'postgresql://forbidden.invalid/never-connect',
            'HTTP_PROXY':'http://forbidden.invalid:1', 'GO_AI_PROVIDERS_JSON':'untrusted-input'})
        jar=http.cookiejar.CookieJar()
        client=build_opener(ProxyHandler({}),HTTPCookieProcessor(jar))
        def call(path,method='GET',body=None,headers=None):
            h={'Content-Type':'application/json',**(headers or {})}
            request=Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=h,method=method)
            try: response=client.open(request,timeout=8)
            except HTTPError as exc: response=exc
            with response:
                data=response.read(); status=response.status
                records.append({'path':path,'method':method,'status':status,
                    'response_sha256':hashlib.sha256(data).hexdigest(),
                    'source_tree_header':response.headers.get('X-GO-Source-Tree')})
                return status,data,dict(response.headers)
        def data(result): return json.loads(result[1])['data']
        def csrf(name): return next(c.value for c in jar if c.name==name)
        def cookie(name): return next((c.value for c in jar if c.name==name),None)
        try:
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                if child.poll() is not None: raise RuntimeError('SERVER_START_FAILED')
                try:
                    if call('/health')[0]==200: break
                except (URLError,TimeoutError,ConnectionError): pass
                time.sleep(.3)
            else: raise RuntimeError('SERVER_START_TIMEOUT')
            credentials=json.loads((state/'credentials.private.json').read_text())
            binding=json.loads((state/'runtime-binding.json').read_text())
            check('fresh SQLite runtime bound to source',binding['source_tree_sha256']==args.expected_tree
                and binding['verified_source_files']==len(fp) and (state/'acceptance.db').is_file())
            check('credential file owner-only',((state/'credentials.private.json').stat().st_mode & 0o777)==0o600)
            status,body,_=call('/__acceptance/binding')
            check('live binding endpoint',status==200 and json.loads(body)['source_tree_sha256']==args.expected_tree)
            check('non-isolated Host rejected',call('/health',headers={'Host':'outside.invalid'})[0]==403)
            mounts={'/go-app/':'frontend/consumer/','/go-admin/':'frontend/admin/',
                    '/supplier-console/':'frontend/supplier/','/console-assets/':'frontend/shared/'}
            for page in ['/go-app/','/go-admin/','/supplier-console/','/go-app/direct.html']:
                status,body,_=call(page)
                mount=next(m for m in mounts if page.startswith(m))
                path=mounts[mount]+(page[len(mount):] or 'index.html')
                check('served exact page '+page,status==200 and hashlib.sha256(body).hexdigest()==fp[path])
                parser=EntryParser(); parser.feed(body.decode())
                for url in parser.refs:
                    parsed=urlsplit(url)
                    check('local entry asset '+url,not parsed.scheme and not parsed.netloc and parsed.path.startswith('/'))
                    mount=next(m for m in mounts if parsed.path.startswith(m))
                    status,asset,_=call(url)
                    check('served exact asset '+url,status==200 and hashlib.sha256(asset).hexdigest()==fp[mounts[mount]+parsed.path[len(mount):]])
            check('consumer unauthenticated',call('/v1/consumer/me')[0]==401)
            c=credentials['consumer']
            check('consumer login',call('/v1/consumer/auth/login','POST',{'email':c['username'],'password':c['password']})[0]==200)
            identity=data(call('/v1/consumer/me'))
            check('consumer identity matches',identity['email']==c['username'])
            for role,actor in [('supplier','SUPPLIER_USER'),('admin','GO_ADMIN')]:
                account=credentials[role]
                check(role+' login',call('/bff/auth/login','POST',{**account,'expected_actor_type':actor})[0]==200)
                me=data(call('/bff/auth/me'))
                check(role+' role',me['actor_type']==actor and me['username']==account['username'])
                if role=='supplier': check('supplier ownership',me['supplier_id']=='sup_acceptance_isolated')
                check('consumer survives console login',data(call('/v1/consumer/me'))['user_id']==identity['user_id'])
                old=cookie('go_refresh')
                check(role+' refresh',call('/bff/auth/refresh','POST',headers={'X-CSRF-Token':csrf('go_csrf')})[0]==200)
                check(role+' refresh rotates token',cookie('go_refresh')!=old)
                wrong='GO_ADMIN' if role=='supplier' else 'SUPPLIER_USER'
                check(role+' wrong-role login rejected',call('/bff/auth/login','POST',{**account,'expected_actor_type':wrong})[0]==401)
                check(role+' wrong-role leaves identity',data(call('/bff/auth/me'))['actor_type']==actor)
                check(role+' logout',call('/bff/auth/logout','POST',headers={'X-CSRF-Token':csrf('go_csrf')})[0]==200)
                check(role+' protected read denied after logout',call('/bff/auth/me')[0]==401)
                check('consumer survives '+role+' logout',data(call('/v1/consumer/me'))['user_id']==identity['user_id'])
            old=cookie('go_consumer_refresh')
            check('consumer refresh',call('/v1/consumer/auth/refresh','POST',headers={'X-CSRF-Token':csrf('go_consumer_csrf')})[0]==200)
            check('consumer refresh rotates token',cookie('go_consumer_refresh')!=old)
            check('consumer logout',call('/v1/consumer/auth/logout','POST',headers={'X-CSRF-Token':csrf('go_consumer_csrf')})[0]==200)
            check('consumer protected read denied after logout',call('/v1/consumer/me')[0]==401)
            check('consumer refresh denied after logout',call('/v1/consumer/auth/refresh','POST')[0] in {401,403})
            # An existing state directory must not be reused or reset.
            repeat=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
            check('existing state preserved',repeat.returncode!=0 and b'FileExistsError' in repeat.stdout)
            public={k:v for k,v in binding.items() if k!='pid'}
            (evidence/'http-runtime-binding.json').write_text(json.dumps(public,indent=2)+'\n')
        finally:
            child.terminate()
            try: child.wait(timeout=15)
            except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
            log.close()
            logtext=logfile.read_text(errors='replace')
            if (state/'credentials.private.json').exists():
                for row in json.loads((state/'credentials.private.json').read_text()).values():
                    logtext=logtext.replace(row['password'],'[REDACTED_TEST_CREDENTIAL]')
            (evidence/'http-server.log').write_text(logtext)
            (evidence/'http-checks.json').write_text(json.dumps({'source_tree_sha256':args.expected_tree,
                'checks':checks,'requests':records,'scope':'LIVE_LOOPBACK_HTTP_ONLY',
                'browser_gate':'HOLD','final_release':'HOLD'},indent=2)+'\n')
    print(json.dumps({'checks_passed':len(checks),'failed':sum(not c['passed'] for c in checks),
        'http_requests':len(records),'scope':'LIVE_LOOPBACK_HTTP_ONLY','browser_gate':'HOLD'}))


if __name__=='__main__': main()
