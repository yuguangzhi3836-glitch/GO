"""Bind the existing bounded 4x4 workload to one explicitly pinned application."""
from pathlib import Path
import importlib.util
import os
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('ride_query_process_pool',ROOT/'ci/process_pool/run.py')
pp=importlib.util.module_from_spec(spec);spec.loader.exec_module(pp)

def bind(head,tree):
    assert re.fullmatch('[0-9a-f]{40}',head) and re.fullmatch('[0-9a-f]{40}',tree)
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==head
    assert subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()==tree
    pp.APP_TREE=tree

if __name__=='__main__':
    bind(os.environ['EXPECTED_HEAD'],os.environ['EXPECTED_APPLICATION_TREE'])
    raise SystemExit(pp.main())
