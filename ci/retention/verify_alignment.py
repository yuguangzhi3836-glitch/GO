"""Verify inherited alignment plus the exact approved 0134 integration overlay."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
record=json.loads((root/'docs/canonical-baseline/PR47_PR48_ALIGNMENT.json').read_text())
current=json.loads((root/'ci/retention/BASELINE.json').read_text())
candidate=json.loads((root/'ci/next-depth/CANDIDATE.json').read_text())

def git(*args):
    return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
def blob(path):
    data=(root/path).read_bytes()
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

actual_tree=git('rev-parse','HEAD:application')
assert actual_tree==current['application_git_tree']==candidate['application_git_tree'],'WRONG_APPLICATION_TREE'
patch_path=root/'ci/journey-v2/ACCEPTANCE_PATCH.json'
patch=json.loads(patch_path.read_text()) if patch_path.exists() else None
repairs=patch['files'] if patch else {}
if patch:
    assert patch['parent_commit']=='2d15536d2b65484e5a1c00067871387cefdfb235'
    assert patch['baseline_application_tree']==record['selected_application_tree']
expected={r['path']:r for r in record['files']}
overlay={'application/'+p:v for p,v in current['approved_application_overrides'].items()}
tracked={p for p in git('ls-files','-z','application').split('\0') if p}
assert tracked==set(expected)|set(repairs)|set(overlay),'SOURCE_FILE_SET_CHANGED'
index={}
for entry in git('ls-files','--stage','-z','application').split('\0'):
    if entry:
        meta,path=entry.split('\t',1);mode,sha,stage=meta.split();assert stage=='0',path;index[path]=(mode,sha)
counts={'BOTH':0,'PR47':0,'PR48':0};changed=[]
for path,row in expected.items():
    assert not (root/path).is_symlink(),path
    if path in overlay:
        selected=overlay[path]['git_blob']; mode=overlay[path].get('mode','100644')
        assert blob(path)==selected,path
        assert index[path]==(mode,selected),path
    else:
        revision=repairs.get(path)
        if revision:
            assert revision['base_git_blob']==row['selected_sha'],path
            assert hashlib.sha256((root/path).read_bytes()).hexdigest()==revision['sha256'],path
        selected=revision['git_blob'] if revision else row['selected_sha']
        assert blob(path)==selected,path
        assert index[path]==(row['selected_mode'],selected),path
    source='sha48' if row['selected_from']=='PR48' else 'sha47'
    assert row['selected_sha']==row[source],path
    if row['selected_from']=='BOTH': assert row['sha47']==row['sha48'],path
    counts[row['selected_from']]+=1
    if row['selected_sha']!=row['sha47']: changed.append(path)
assert sorted(changed)==['application/frontend/shared/app.js'],changed
assert counts=={'BOTH':1264,'PR47':35,'PR48':1},counts
for path in set(repairs)-set(expected):
    if path in overlay: continue
    revision=repairs[path]
    assert revision['base_git_blob'] is None and path.startswith('application/')
    assert not (root/path).is_symlink()
    assert blob(path)==revision['git_blob']
    assert hashlib.sha256((root/path).read_bytes()).hexdigest()==revision['sha256']
    assert index[path]==(revision['mode'],revision['git_blob'])
for path,row in overlay.items():
    if path not in expected and path not in repairs:
        assert blob(path)==row['git_blob'],path
        assert index[path]==(row.get('mode','100644'),row['git_blob']),path
for row in record['archived_pr48_tooling']:
    assert blob(row['path'])==row['git_blob'],'HISTORY_CHANGED:'+row['path']
assert not (root/'.github/workflows/depth41-journey.yml').exists(),'OLD_JOURNEY_WORKFLOW_MUST_REMAIN_INACTIVE'
migration=(root/'application/alembic/versions/0134_flight_status_width.py').read_text()
assert 'revision = "0134_flight_status_width"' in migration and 'down_revision = "0133_flight_change_plan"' in migration
report={'commit':git('rev-parse','HEAD'),'product_candidate_commit':current['product_candidate_commit'],
        'application_tree':actual_tree,'selected_source_files':len(tracked),'retained_baseline_files':len(expected),
        'registered_acceptance_repairs':len(repairs),'approved_integration_overrides':sorted(overlay),
        'selection_counts':counts,'pr47_application_changes':changed,'archived_tooling_files':len(record['archived_pr48_tooling']),
        'alignment':'PASS','migration_head':current['migration_head'],'historical_pass_transferred':False,
        'full_three_end_ux':'HOLD','six_vertical_closed_loop':'HOLD','sealed_node':'HOLD','final_release':'HOLD'}
if len(sys.argv)>1:
    out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
