"""C13 exact candidate recorder. Start only after the final C14 acceptance record."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3]
APP=ROOT/'application'
OUT=Path(__file__).resolve().parent
PYTHON=ROOT.parent/'venv/bin/python'
MANIFEST=ROOT/'evidence/v70-round2-20260914/CANDIDATE_SOURCE.json'

def utc():return datetime.now(timezone.utc).isoformat()
def fingerprint():
    manifest=json.loads(MANIFEST.read_text())
    hashes={}
    for rel,entry in manifest['files'].items():
        p=ROOT/rel
        assert p.is_file() and not p.is_symlink(),rel
        raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        assert digest==entry['sha256'],rel
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==entry['sha'],rel
        hashes[rel]=digest
    nodes={}
    for rel,entry in manifest['files'].items():
        path=rel.removeprefix('application/').split('/');node=nodes
        for part in path[:-1]:node=node.setdefault(part,{})
        node[path[-1]]=(entry['mode'],entry['sha'])
    def git_tree(node):
        rows=[]
        for name,value in node.items():
            directory=isinstance(value,dict)
            mode,sha=('40000',git_tree(value)) if directory else value
            rows.append((name+('/' if directory else ''),mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)))
        payload=b''.join(value for _,value in sorted(rows))
        return hashlib.sha1(b'tree '+str(len(payload)).encode()+b'\0'+payload).hexdigest()
    assert git_tree(nodes)==manifest['application_git_tree'],'GIT_TREE_MISMATCH'
    tree=hashlib.sha256(''.join(f'{p.removeprefix("application/")}\0{h}\n' for p,h in sorted(hashes.items())).encode()).hexdigest()
    assert tree==manifest['source_tree_sha256'],tree
    return {'checked_at':utc(),'source_anchor':manifest['source_anchor'],
        'application_git_tree':manifest['application_git_tree'],'source_tree_sha256':tree,
        'source_files':len(hashes),'candidate_manifest_sha256':hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        'files_sha256':hashes}

def run(name,selected):
    before=fingerprint();(OUT/(name+'.before.json')).write_text(json.dumps(before,indent=2)+'\n')
    env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='src',GO_TEST_DB_PATH=f'/tmp/go-r2-c13-{name}-{os.getpid()}.db')
    command=[str(PYTHON),'-m','pytest','-c','pyproject.toml','-p','no:cacheprovider','-ra','--tb=short',*selected,
        '--junitxml='+str(OUT/(name+'.xml'))]
    record={'reviewer':'/root/c13_independent','started_at':utc(),'command':command,'cwd':str(APP),
        'environment':{k:env[k] for k in ('PYTHONDONTWRITEBYTECODE','PYTHONPATH','GO_TEST_DB_PATH')},
        'worker_settings':'UNCHANGED_DEFAULTS','test_and_tool_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [OUT/'run_independent.py',OUT/'conftest.py',OUT/'test_independent_boundaries.py',ROOT/'ci/round2/validate_ledger.py']},'source_anchor':before['source_anchor'],
        'source_tree_sha256':before['source_tree_sha256'],'application_git_tree':before['application_git_tree']}
    (OUT/(name+'.command.json')).write_text(json.dumps(record,indent=2)+'\n')
    with (OUT/(name+'.log')).open('w') as log:
        result=subprocess.run(command,cwd=APP,env=env,stdout=log,stderr=subprocess.STDOUT)
    record.update(finished_at=utc(),exit_code=result.returncode)
    after=fingerprint();(OUT/(name+'.after.json')).write_text(json.dumps(after,indent=2)+'\n')
    record['source_unchanged']=before['files_sha256']==after['files_sha256']
    record['log_sha256']=hashlib.sha256((OUT/(name+'.log')).read_bytes()).hexdigest()
    (OUT/(name+'.result.json')).write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record),flush=True)
    return result.returncode

SCOPE=[
 'tests/test_v70_round2_c01_mixed_funding.py','tests/test_v70_round2_c02_partial_party.py',
 'tests/test_sprint3b_rail.py','tests/test_depth22_rail_resolution.py',
 'tests/test_depth23_capacity.py::test_rail_change_holds_both_dates_until_result_then_releases_correct_pool',
 'tests/test_v70_round2_c04_rental_receipts.py','tests/test_v70_round2_c05_recovery_fulfillment.py',
 'tests/test_sprint3d_attractions.py','tests/test_depth20_attraction_contract.py','tests/test_depth26_attraction_terms.py',
 'tests/test_depth21_refund_recovery.py::test_concurrent_refund_has_one_executor_and_blocks_change_or_redeem[ATTRACTION]',
 'tests/test_depth23_capacity.py::test_attraction_change_and_redemption_retain_current_session_capacity',
 'tests/test_round2_c07_explicit_preferences.py','tests/test_travel_intelligence_p0.py',
 'tests/test_wave03_c07_c09_authority_contract.py','tests/test_personal_travel_vault.py','tests/test_parent_p0_travel_intelligence_hotel_infra.py',
 'tests/go_ai/test_c08_audit_commit_failure.py','tests/go_ai/test_c08_synthesis_audit_finalization.py','tests/test_go_ai_multimodel.py',
 'tests/judgment/test_round2_evidence_authority.py','tests/test_sprint1p_judgment_runtime.py',
 'tests/journey/test_c10_attachment_canonical_facts.py','tests/journey/test_c10_current_status_projection.py',
 'tests/test_c11_idempotency_completion_guard.py',
 '../evidence/v70-round2-20260914/c13/test_independent_boundaries.py',
]
if __name__=='__main__':
    # Parent/C14 sends the final record explicitly; preflight does not manufacture C14 authority.
    c14=Path(sys.argv[1]).resolve(); raw=c14.read_text(); record=json.loads(raw)
    assert record['status']=='PASS_SCOPED' and record['application_git_tree']=='740d026e3723f5da015342ead3394969629541df', 'Final exact-candidate C14 PASS missing'
    assert hashlib.sha256(c14.read_bytes()).hexdigest()=='6406436910f6c5cb7f1bf6684fbb35e7069f8a2787dedae110b9108dce549c2c'
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest()==record['candidate_manifest_sha256']
    for rel,digest in record['integration_files_sha256'].items():
        assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest,rel
    assert datetime.fromisoformat(record['completed_at_utc'])<datetime.now(timezone.utc)
    (OUT/'C14_RECEIPT_BINDING.json').write_text(json.dumps({'path':str(c14.relative_to(ROOT)),
        'sha256':hashlib.sha256(raw.encode()).hexdigest(),'observed_at':utc(),'record':record},indent=2)+'\n')
    raise SystemExit(run('independent-scopes',SCOPE))
