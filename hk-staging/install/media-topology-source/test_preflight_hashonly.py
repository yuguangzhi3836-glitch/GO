import hashlib,importlib.util,json,os
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('preflight',Path(__file__).with_name('preflight_hashonly.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class HashOnlyTests(unittest.TestCase):
 def test_regular_file_returns_hash_metadata_not_content(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'config';raw=b'NEVER_EXPORT_PRIVATE_CONTENT';p.write_bytes(raw);p.chmod(0o600)
   dirs={};r=m.hash_file(str(p),dirs)
   self.assertEqual(r['sha256'],hashlib.sha256(raw).hexdigest());self.assertEqual(r['mode'],0o600)
   self.assertNotIn(raw.decode(),json.dumps({'files':r,'directories':dirs}));self.assertIn('/',dirs)
 def test_symlink_file_and_parent_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);real=root/'real';real.mkdir();(real/'config').write_text('secret')
   (root/'link').symlink_to(real,target_is_directory=True);(root/'file').symlink_to(real/'config')
   for p in (root/'link/config',root/'file'):
    with self.assertRaises(OSError):m.hash_file(str(p),{})
 def test_wrong_hostname_never_opens_any_file(self):
  with patch.object(m.socket,'gethostname',return_value='WRONG'),patch.object(m,'hash_file') as read:
   with self.assertRaisesRegex(m.Reject,'hostname_mismatch'):m.observe('go-cc')
   read.assert_not_called()
 def test_unknown_role_never_opens_any_file(self):
  with patch.object(m,'hash_file') as read:
   with self.assertRaises(m.Reject):m.observe('arbitrary')
   read.assert_not_called()
 def test_directory_file_and_oversize_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   with self.assertRaises(m.Reject):m.hash_file(str(root),{})
   f=root/'large';f.write_bytes(b'12345')
   with patch.object(m,'MAX_FILE_BYTES',4):
    with self.assertRaises(m.Reject):m.hash_file(str(f),{})
if __name__=='__main__':unittest.main()
