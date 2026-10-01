import os
import subprocess
import unittest
from pathlib import Path
from git_transport import GitTransport
import test_flow as fixtures

class GitFlowTests(fixtures.FlowTests):
    # Retest all flow failures against local bare Git, no network or real identities.
    def setUp(self):
        super().setUp()
        def transport(kind):
            root=Path(self.tmp.name)/kind;root.mkdir()
            seed=root/'seed';bare=root/'remote.git'
            subprocess.run(['git','init','-q','-b','main',str(seed)],check=True)
            (seed/'README').write_text('isolated fixture\n')
            for args in [('add','README'),('-c','user.name=Fixture','-c','user.email=fixture@localhost','commit','-qm','fixture')]:
                subprocess.run(['git','-C',str(seed),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            subprocess.run(['git','clone','--bare','-q',str(seed),str(bare)],check=True)
            return GitTransport(str(bare),'main',kind,git_env=os.environ)
        self.tasks=transport('tasks');self.evidence=transport('evidence')
    # Only the real transport-independent end-to-end path is inherited below.
    def test_git_immutable_conflict(self):
        self.tasks.create('tasks/fixture-task.json',b'one')
        from channel import Reject
        with self.assertRaises(Reject):self.tasks.create('tasks/fixture-task.json',b'two')
        self.assertEqual(self.tasks.read('tasks/fixture-task.json'),b'one')

# Avoid inheriting tests that deliberately inject MemoryTransport-specific faults.
for name in list(fixtures.FlowTests.__dict__):
    if name.startswith('test_') and name!='test_e2e_initialize_sign_publish_poll_collect':
        setattr(GitFlowTests,name,None)
