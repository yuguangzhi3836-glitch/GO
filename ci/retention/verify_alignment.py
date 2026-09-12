"""Verify every selected source blob and preserve archived journey tooling."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
record=json.loads((root/'docs/canonical-baseline/PR47_PR48_ALIGNMENT.json').read_text())
def git(*args):
    return subprocess.check_output(['git',*args],cwd=root).decode().strip()
def blob(path):
    data=(root/path).read_bytes()
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
actual_tree=git('rev-parse','HEAD:application')
assert actual_tree==record['selected_application_tree'],'WRONG_APPLICATION_TREE'
expected={r['path']:r for r in record['files']}
tracked={p for p in git('ls-files','-z','application').split('\0') if p}
assert tracked==set(expected),'SOURCE_FILE_SET_CHANGED'
index={}
for entry in git('ls-files','--stage','-z','application').split('\0'):
    if entry:
        meta,path=entry.split('\t',1); mode,sha,stage=meta.split()
        assert stage=='0',path
        index[path]=(mode,sha)
counts={'BOTH':0,'PR47':0,'PR48':0}
changed=[]
for path,row in expected.items():
    assert not (root/path).is_symlink(),path
    assert blob(path)==row['selected_sha'],path
    assert index[path]==(row['selected_mode'],row['selected_sha']),path
    source='sha48' if row['selected_from']=='PR48' else 'sha47'
    assert row['selected_sha']==row[source],path
    if row['selected_from']=='BOTH':
        assert row['sha47']==row['sha48'],path
    counts[row['selected_from']]+=1
    if row['selected_sha']!=row['sha47']:
        changed.append(path)
assert sorted(changed)==['application/frontend/shared/app.js'],changed
assert counts=={'BOTH':1264,'PR47':35,'PR48':1},counts
for row in record['archived_pr48_tooling']:
    assert blob(row['path'])==row['git_blob'],'HISTORY_CHANGED:'+row['path']
assert not (root/'.github/workflows/depth41-journey.yml').exists(),'OLD_JOURNEY_WORKFLOW_MUST_REMAIN_INACTIVE'
report={'commit':git('rev-parse','HEAD'),'application_tree':actual_tree,
        'selected_source_files':len(expected),'selection_counts':counts,
        'pr47_application_changes':changed,'archived_tooling_files':len(record['archived_pr48_tooling']),
        'alignment':'PASS','historical_pass_transferred':False,
        'full_three_end_ux':'HOLD','six_vertical_closed_loop':'HOLD',
        'sealed_node':'HOLD','final_release':'HOLD'}
if len(sys.argv)>1:
    out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
