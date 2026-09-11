#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BIND=ROOT/'WAVE07_FRG02_RELEASE_BINDING_20260831.json'
INCLUDE=('src','tests','scripts','alembic','governance')
EXCLUDE={'scripts/v70_source_tree_binding.py'}
RELEASE_ID='GO-V7.0-PARALLEL-WAVE07-FRG02-20260831'
PARENT_RELEASE_ID='GO-V7.0-PARALLEL-WAVE07-20260831'
PARENT_ZIP_SHA='638d27279c6d06063a4ae9a725a7c2a172b9874e183239388faf01a061efee70'
PARENT_SOURCE_TREE_SHA='7505db171b0558a3e5fe475988bcf67a1b0f7b139ba65b50e38ce7b75a248888'
SOURCE_HEAD='0114_ext_truth_incident_hard'
SOURCE_DOWN_REVISION='0113_ext_truth_ops_20260901'
REVISION_COUNT=114
STAGING_PREDEPLOY_HEAD='0111_test_account_expiry'

def digest():
    h=hashlib.sha256(); files=[]
    for base in INCLUDE:
        p=ROOT/base
        if not p.exists(): continue
        files += [x for x in p.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix!='.pyc']
    for p in sorted(files,key=lambda x:x.relative_to(ROOT).as_posix()):
        rel=p.relative_to(ROOT).as_posix()
        if rel in EXCLUDE: continue
        h.update(rel.encode()); h.update(b'\0'); h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--write',action='store_true'); ap.add_argument('--verify',action='store_true'); a=ap.parse_args()
    sha=digest()
    if a.write:
        data={
          'release_id':RELEASE_ID,
          'parent_release_id':PARENT_RELEASE_ID,
          'immutable_parent_zip_sha256':PARENT_ZIP_SHA,
          'immutable_parent_source_tree_sha256':PARENT_SOURCE_TREE_SHA,
          'source_tree_sha256':sha,
          'source_tree_scope':list(INCLUDE),
          'migration_source_head':SOURCE_HEAD,
          'migration_source_down_revision':SOURCE_DOWN_REVISION,
          'migration_revision_count':REVISION_COUNT,
          'staging_predeploy_confirmed_head':STAGING_PREDEPLOY_HEAD,
          'candidate_zip_sha_binding':'EXTERNAL_GATE_INPUT_NO_SELF_HASH_IN_SOURCE_TREE',
          'deployment_status':'NOT_DEPLOYED'
        }
        BIND.write_text(json.dumps(data,indent=2)+'\n'); print(sha); return
    if a.verify:
        d=json.loads(BIND.read_text())
        assert d['source_tree_sha256']==sha,(d['source_tree_sha256'],sha)
        assert d['release_id']==RELEASE_ID
        assert d['parent_release_id']==PARENT_RELEASE_ID
        assert d['immutable_parent_zip_sha256']==PARENT_ZIP_SHA
        assert d['immutable_parent_source_tree_sha256']==PARENT_SOURCE_TREE_SHA
        assert d['migration_source_head']==SOURCE_HEAD
        assert d['migration_source_down_revision']==SOURCE_DOWN_REVISION
        assert d['migration_revision_count']==REVISION_COUNT
        assert d['staging_predeploy_confirmed_head']==STAGING_PREDEPLOY_HEAD
        assert d['deployment_status']=='NOT_DEPLOYED'
        print('SOURCE_TREE_BINDING_OK='+sha); return
    print(sha)
if __name__=='__main__': main()
