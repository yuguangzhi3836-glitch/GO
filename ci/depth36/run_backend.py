"""Partition the complete pytest collection by source file, preserving all tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pytest

p=argparse.ArgumentParser()
p.add_argument('--shard',type=int,required=True)
p.add_argument('--total',type=int,required=True)
p.add_argument('--evidence',type=Path,required=True)
a=p.parse_args()
assert 0 <= a.shard < a.total
a.evidence.mkdir(exist_ok=True)

class Inventory:
    def __init__(self):
        self.all=[]; self.selected=[]; self.reports={}

    def pytest_collection_modifyitems(self,config,items):
        self.all=[i.nodeid for i in items]
        assert len(self.all)==len(set(self.all)) and self.all
        selected=[]; deselected=[]
        for item in items:
            file=item.nodeid.split('::',1)[0]
            owner=int(hashlib.sha256(file.encode()).hexdigest()[:8],16)%a.total
            (selected if owner==a.shard else deselected).append(item)
        assert selected
        self.selected=[i.nodeid for i in selected]
        config.hook.pytest_deselected(items=deselected)
        items[:]=selected
        self.write(None)

    def pytest_runtest_logreport(self,report):
        self.reports.setdefault(report.nodeid,[]).append({'when':report.when,'outcome':report.outcome})

    def pytest_sessionfinish(self,session,exitstatus):
        self.write(int(exitstatus))

    def write(self,exitstatus):
        value={'candidate':os.environ['SEALED_CANDIDATE'],
               'source_tree_sha256':os.environ['EXPECTED_SOURCE_TREE'],
               'shard':a.shard,'total_shards':a.total,
               'all_nodeids':self.all,'selected_nodeids':self.selected,
               'reports':self.reports,'pytest_exitstatus':exitstatus}
        (a.evidence/'backend-inventory.json').write_text(json.dumps(value,indent=2)+'\n')

raise SystemExit(pytest.main(['--maxfail=25','--durations=20',
    '--junitxml='+str(a.evidence/'backend-full.xml')],plugins=[Inventory()]))
