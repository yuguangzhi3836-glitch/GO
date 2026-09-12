"""Preserve exact, hash-pinned CI evidence on the existing Draft PR branch."""
import base64, hashlib, io, json, os, pathlib, subprocess, urllib.parse, urllib.request, zipfile

REPO='yuguangzhi3836-glitch/GO'
BRANCH='fix/canonical-parent-retention-20260912'
SOURCE='800538c1714dd3e50f3abf8c97964a2ee8ba4e72'
APP_TREE='219e4ca8a7176e3ff4c32af5524e322635c2d845'
SOURCE_HASH='be152b85b7b55ae6cc661446b20a309fc4c004c1c0c25f7b0c74fe0ea1c664da'
RUN=34694860505
PREFIX='evidence/depth42-go-trip'
HEAD=os.environ['GITHUB_SHA']
TOKEN=os.environ['GO_ARCHIVE_TOKEN']
assert os.environ['GITHUB_REPOSITORY']==REPO
assert os.environ['GITHUB_REF']=='refs/heads/'+BRANCH
assert subprocess.check_output(['git','rev-parse','HEAD:application'],text=True).strip()==APP_TREE

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        out=super().redirect_request(req,fp,code,msg,headers,newurl)
        if out and urllib.parse.urlsplit(req.full_url).netloc!=urllib.parse.urlsplit(newurl).netloc:
            out.remove_header('Authorization')
        return out

opener=urllib.request.build_opener(SafeRedirect())
def request(path, method='GET', data=None, raw=False):
    url='https://api.github.com/repos/'+REPO+'/'+path
    headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'}
    payload=json.dumps(data).encode() if data is not None else None
    with opener.open(urllib.request.Request(url,payload,headers,method=method),timeout=60) as response:
        value=response.read(32*1024*1024+1)
    assert len(value)<=32*1024*1024
    return value if raw else json.loads(value)

def encode(value):return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
def sha(data):return hashlib.sha256(data).hexdigest()
def gitsha(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def put_blob(data):
    result=request('git/blobs','POST',{'content':base64.b64encode(data).decode(),'encoding':'base64'})
    assert result['sha']==gitsha(data)
    copied=request('git/blobs/'+result['sha'])
    assert base64.b64decode(copied['content'])==data
    return result['sha']

assert request('git/ref/heads/'+BRANCH)['object']['sha']==HEAD,'BRANCH_MOVED'
pr=request('pulls/47');assert pr['draft'] and pr['head']['sha']==HEAD and not pr['merged']
run=request('actions/runs/'+str(RUN));assert run['head_sha']==SOURCE and run['conclusion']=='success'
jobs=request('actions/runs/'+str(RUN)+'/jobs?per_page=100')['jobs']
assert len(jobs)==6 and all(x['conclusion']=='success' for x in jobs)
source_commit=request('git/commits/'+SOURCE)
source_tree=request('git/trees/'+source_commit['tree']['sha'])
assert next(x['sha'] for x in source_tree['tree'] if x['path']=='application')==APP_TREE
files={PREFIX+'/RUN.json':encode(run),PREFIX+'/JOBS.json':encode(jobs)}
artifacts=json.loads(pathlib.Path('packaging/depth41-journey-archive/ARTIFACTS.json').read_text())
inventory=[];reports=[];browser=None
for item in artifacts:
    aid=item['id'];meta=request('actions/artifacts/'+str(aid))
    assert not meta['expired'] and meta['workflow_run']['head_sha']==item['head_sha']
    assert meta['workflow_run']['id']==item['run_id'] and meta['size_in_bytes']==item['size']
    assert meta['digest']=='sha256:'+item['sha256']
    data=request('actions/artifacts/'+str(aid)+'/zip',raw=True)
    assert len(data)==item['size'] and sha(data)==item['sha256']
    z=zipfile.ZipFile(io.BytesIO(data));assert z.testzip() is None
    names=z.namelist();assert len(names)==len(set(names))
    assert not any('private' in x.lower() or x.endswith(('.db','.sqlite3')) for x in names)
    if 'SHA256.json' in names:
        hashes=json.loads(z.read('SHA256.json'))
        assert set(names)==set(hashes)|{'SHA256.json'}
        for name,digest in hashes.items():assert sha(z.read(name))==digest
    path=PREFIX+'/'+str(item['run_id'])+'/'+str(aid)+'.zip';files[path]=data
    item['archive_path']=path
    if item['run_id']==RUN:
        if 'browser-results.json' in names:
            browser=json.loads(z.read('browser-results.json'))
            assert browser['commit']==SOURCE and browser['source_tree_sha256']==SOURCE_HASH
            assert not browser['failed'] and len(browser['browser_tests'])+len(browser['journeys'])==39
            assert len(browser['detail_viewports'])==72 and all(x['result']=='PASS' for x in browser['detail_viewports'])
            audit=json.loads(z.read('independent-ledger-audit.json'))
            assert audit['commit']==SOURCE and audit['result']=='PASS' and len(audit['orders'])==6
            for name in ['browser-results.json','independent-ledger-audit.json','source-binding.json','source-fingerprint.json','SHA256.json']:
                files[PREFIX+'/current/'+name]=z.read(name)
        elif 'tests/RESULT.json' in names:
            r=json.loads(z.read('tests/RESULT.json'));assert r['exit_code']==0
            reports.append(r);inventory.append(json.loads(z.read('tests/TEST_FILE_INVENTORY.json')))
assert browser is not None and len(reports)==4
selected=[p for x in inventory for p in x['selected']]
assert len(selected)==len(set(selected)) and all(set(x['all'])==set(selected) for x in inventory)
totals={k:sum(x[k] for x in reports) for k in ['tests','passed','skipped','failures','errors']}
assert totals=={'tests':1729,'passed':1723,'skipped':6,'failures':0,'errors':0}
summary={'source_commit':SOURCE,'application_git_tree':APP_TREE,'source_tree_sha256':SOURCE_HASH,
 'producer_run':RUN,'archive_workflow_commit':HEAD,'archive_workflow_run':os.environ['GITHUB_RUN_ID'],
 'python':totals,'python_files':len(selected),'browser_scenarios':39,'detail_viewports':72,
 'isolated_original_payment_refund_orders':6,'historical_results_transferred':False,
 'hong_kong':'NOT_ACCESSED','production':'HOLD','sealed_node':'HOLD','final_release':'HOLD',
 'artifacts':artifacts}
files[PREFIX+'/ARCHIVE_MANIFEST.json']=encode(summary)
files[PREFIX+'/FILE_SHA256.json']=encode({p:sha(data) for p,data in sorted(files.items())})
entries=[]
for path,data in sorted(files.items()):
    assert path.startswith(PREFIX+'/') and '..' not in pathlib.PurePosixPath(path).parts
    entries.append({'path':path,'type':'blob','mode':'100644','sha':put_blob(data)})
base=request('git/commits/'+HEAD)
tree=request('git/trees','POST',{'base_tree':base['tree']['sha'],'tree':entries})
assert next(x['sha'] for x in request('git/trees/'+tree['sha'])['tree'] if x['path']=='application')==APP_TREE
commit=request('git/commits','POST',{'message':'docs: preserve exact three-end evidence and independent refund ledger [skip ci]','parents':[HEAD],'tree':tree['sha']})
assert request('git/ref/heads/'+BRANCH)['object']['sha']==HEAD,'BRANCH_MOVED_BEFORE_ARCHIVE'
request('git/refs/heads/'+BRANCH,'PATCH',{'sha':commit['sha'],'force':False})
assert request('git/ref/heads/'+BRANCH)['object']['sha']==commit['sha']
receipt={'archive_commit':commit['sha'],'source_commit':SOURCE,'application_git_tree':APP_TREE,
 'files':len(files),'archive_file_sha256':sha(files[PREFIX+'/FILE_SHA256.json']),'all_blob_bytes_read_back':'PASS'}
pathlib.Path('ARCHIVE_RECEIPT.json').write_bytes(encode(receipt));print(json.dumps(receipt))
