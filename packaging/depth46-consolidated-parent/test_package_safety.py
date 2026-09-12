"""Archive corruption and unsafe restoration must fail before producing a parent."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from reconstruct_parent import NAME, reconstruct
from verify_parent import safe_extract


class PackageSafety(unittest.TestCase):
    def test_split_roundtrip_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'complete-parent-fixture'
            part = NAME + '.part000'
            (root / part).write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            (root / 'PARENT_PARTS.json').write_text(json.dumps({'zip_file': NAME, 'zip_bytes': len(data), 'zip_sha256': digest,
                'parts': [{'name': part, 'bytes': len(data), 'sha256': digest}]}))
            target = root / 'parent.zip'
            self.assertEqual(reconstruct(root, target)['status'], 'PASS')
            self.assertEqual(target.read_bytes(), data)
            with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
                reconstruct(root, target)
            (root / part).write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'PART_HASH'):
                reconstruct(root, root / 'corrupt.zip')
            self.assertFalse((root / 'corrupt.zip').exists())

    def test_archive_traversal_and_symlink_rejected(self):
        for filename, mode in [('../outside', 0o100644), ('link', 0o120777)]:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = root / 'bad.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    entry = zipfile.ZipInfo(filename)
                    entry.external_attr = mode << 16
                    z.writestr(entry, 'payload')
                with self.assertRaises(ValueError):
                    safe_extract(archive, root / 'restored')
                self.assertFalse((root / 'restored').exists())

    def test_restore_preserves_executable_and_refuses_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'good.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                entry = zipfile.ZipInfo('bin/tool')
                entry.external_attr = 0o100755 << 16
                z.writestr(entry, 'payload')
            target = root / 'restored'
            safe_extract(archive, target)
            self.assertEqual((target / 'bin/tool').stat().st_mode & 0o777, 0o755)
            with self.assertRaisesRegex(ValueError, 'DESTINATION_EXISTS'):
                safe_extract(archive, target)


if __name__ == '__main__':
    unittest.main()
