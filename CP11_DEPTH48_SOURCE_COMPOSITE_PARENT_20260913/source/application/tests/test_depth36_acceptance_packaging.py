"""Offline safety/restore tests; run with unittest without application dependencies."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from acceptance_runtime import isolated_environment, network_guard, verify_source, tree_hash
from acceptance_bundle import build, verify


class RuntimePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'; self.root.mkdir()
        (self.root / 'app.py').write_text('VALUE = 1\n')
        self.fp = {'app.py': hashlib.sha256((self.root / 'app.py').read_bytes()).hexdigest()}
        self.tree = tree_hash(self.fp)

    def test_roundtrip_and_reproducible_bytes(self):
        first, second = self.base / 'first.zip', self.base / 'second.zip'
        info = build(self.root, self.fp, self.tree, first)
        build(self.root, self.fp, self.tree, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        restored = self.base / 'restored'
        verify(first, info['archive_sha256'], self.tree, restored)
        self.assertEqual((restored/'source/app.py').read_bytes(), (self.root/'app.py').read_bytes())

    def test_changed_source_is_rejected(self):
        (self.root/'app.py').write_text('VALUE = 2\n')
        with self.assertRaisesRegex(ValueError, 'SOURCE_FILE_MISMATCH'):
            verify_source(self.root, self.fp, self.tree)

    def test_untracked_configuration_is_rejected(self):
        (self.root/'.env').write_text('DATABASE_URL=postgresql://not-a-test.invalid/db')
        with self.assertRaisesRegex(ValueError, 'UNTRACKED_SOURCE_FILE'):
            verify_source(self.root, self.fp, self.tree)

    def test_untracked_bytecode_is_rejected(self):
        (self.root/'__pycache__').mkdir()
        (self.root/'__pycache__/app.pyc').write_bytes(b'not-a-trusted-cache')
        with self.assertRaisesRegex(ValueError, 'UNTRACKED_SOURCE_FILE'):
            verify_source(self.root, self.fp, self.tree)

    def test_source_symlink_is_rejected(self):
        (self.base/'outside').write_text('VALUE = 1\n')
        (self.root/'app.py').unlink()
        (self.root/'app.py').symlink_to(self.base/'outside')
        with self.assertRaisesRegex(ValueError, 'SOURCE_SYMLINK'):
            verify_source(self.root, self.fp, self.tree)

    def test_wrong_pinned_tree_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SOURCE_TREE_MISMATCH'):
            verify_source(self.root, self.fp, '0'*64)

    def test_existing_output_is_preserved(self):
        target=self.base/'bundle.zip'; target.write_bytes(b'prior-sealed-artifact')
        with self.assertRaises(FileExistsError): build(self.root,self.fp,self.tree,target)
        self.assertEqual(target.read_bytes(),b'prior-sealed-artifact')

    def test_archive_tamper_and_unlisted_member_rejected(self):
        target=self.base/'bundle.zip'; info=build(self.root,self.fp,self.tree,target)
        with zipfile.ZipFile(target,'a') as z: z.writestr('../escape.txt','tampered')
        with self.assertRaisesRegex(ValueError,'ARCHIVE_CHECKSUM_MISMATCH'):
            verify(target,info['archive_sha256'],self.tree)
        with self.assertRaisesRegex(ValueError,'UNSAFE_ARCHIVE_MEMBERS'):
            verify(target,hashlib.sha256(target.read_bytes()).hexdigest(),self.tree)

    def test_inherited_credentials_and_database_are_not_propagated(self):
        credentials={r:{'username':r,'password':'disposable-unit-test'} for r in ['admin','supplier']}
        env=isolated_environment(self.base,credentials,{'PATH':'/usr/bin','DATABASE_URL':'production',
            'HTTP_PROXY':'untrusted','AWS_ACCESS_KEY_ID':'not-real','PYTHONPATH':'untrusted'})
        self.assertEqual(env['DATABASE_URL'],'sqlite+pysqlite:///'+str(self.base/'acceptance.db'))
        for key in ('HTTP_PROXY','AWS_ACCESS_KEY_ID','PYTHONPATH'): self.assertNotIn(key,env)
        self.assertEqual(env['VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED'],'false')

    def test_outbound_operations_are_denied(self):
        code = """
import sys,socket
sys.path.insert(0,sys.argv[1])
from acceptance_runtime import network_guard
sys.addaudithook(network_guard)
operations=[lambda:socket.socket().connect(('127.0.0.1',9)),
            lambda:socket.socket(socket.AF_INET,socket.SOCK_DGRAM).sendto(b'x',('127.0.0.1',9)),
            lambda:socket.getaddrinfo('example.invalid',443)]
for operation in operations:
    try: operation()
    except PermissionError as exc:
        assert str(exc)=='ISOLATED_RUNTIME_OUTBOUND_DISABLED'
    else: raise AssertionError('operation was not blocked')
print('THREE_ACTUAL_NETWORK_OPERATIONS_DENIED')
"""
        result=subprocess.run([sys.executable,'-B','-c',code,str(Path(__file__).resolve().parents[1]/'scripts')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('THREE_ACTUAL_NETWORK_OPERATIONS_DENIED',result.stdout)


if __name__ == '__main__': unittest.main()
