"""Verify the unique checkout in place; never restore old application files."""
import hashlib, json, pathlib, shutil, subprocess, sys

root=pathlib.Path(__file__).resolve().parents[2]
out=root/'journey-evidence'
out.mkdir(exist_ok=True)
subprocess.run([sys.executable,str(root/'ci/retention/verify_source.py'),str(out/'source')],check=True,cwd=root)
subprocess.run([sys.executable,str(root/'ci/retention/verify_alignment.py'),str(out/'alignment.json')],check=True,cwd=root)
retention=json.loads((out/'source/RETENTION_RESULT.json').read_text())
patch=json.loads((root/'ci/journey-v2/ACCEPTANCE_PATCH.json').read_text())
shutil.copyfile(out/'source/SOURCE_FINGERPRINT.json',out/'source-fingerprint.json')
binding={'schema':'go.depth41.current-journey.v2',
    'candidate_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip(),
    'application_git_tree':subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=root).decode().strip(),
    'parent_commit':patch['parent_commit'], 'source_tree_sha256':retention['source_tree_sha256'],
    'source_files':retention['source_files'], 'test_source':'CURRENT_CHECKOUT_ONLY',
    'tool_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in pathlib.Path(__file__).parent.iterdir() if p.is_file()},
    'historical_results_transferred':False,'hong_kong':'NOT_ACCESSED','production':'HOLD'}
(out/'source-binding.json').write_text(json.dumps(binding,indent=2)+'\n')
print(json.dumps(binding))
