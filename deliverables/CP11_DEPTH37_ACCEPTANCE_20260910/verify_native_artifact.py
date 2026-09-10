"""Validate a CI artifact transport and all fingerprinted members before use."""
import argparse,hashlib,json,zipfile
from pathlib import Path,PurePosixPath
p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('output',type=Path);p.add_argument('--sha256',required=True);p.add_argument('--candidate',required=True);p.add_argument('--source',required=True);a=p.parse_args()
sha=lambda b:hashlib.sha256(b).hexdigest();assert sha(a.archive.read_bytes())==a.sha256.removeprefix('sha256:'),'ZIP_DIGEST_MISMATCH';assert not a.output.exists(),'NEW_OUTPUT_REQUIRED'
with zipfile.ZipFile(a.archive) as z:
    for item in z.infolist():
        path=PurePosixPath(item.filename)
        assert not path.is_absolute() and '..' not in path.parts and '\\' not in item.filename,'UNSAFE_MEMBER'
        assert (item.external_attr>>16)&0o170000!=0o120000,'SYMLINK_MEMBER'
    z.extractall(a.output)
fp=json.loads((a.output/'artifact-fingerprints.json').read_text());verified=[]
for name,expected in fp.items():
    path=PurePosixPath(name);assert not path.is_absolute() and '..' not in path.parts
    file=a.output/name;raw=file.read_bytes();assert len(raw)==expected['bytes'],name;assert sha(raw)==expected['sha256'],name;verified.append(name)
file=a.output/'source-binding.json'
if not file.exists():file=a.output/'artifact-binding.json'
binding=json.loads(file.read_text());assert binding['candidate']==a.candidate,'CANDIDATE_MISMATCH';assert binding['source_tree_sha256']==a.source,'SOURCE_MISMATCH'
report={'zip_sha256':a.sha256.removeprefix('sha256:'),'zip_bytes':a.archive.stat().st_size,'verified_members':verified,'binding':binding,'status':'PASS'}
(a.output/'LOCAL_TRANSPORT_VERIFICATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
