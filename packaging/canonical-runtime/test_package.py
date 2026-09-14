import io
import pathlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import package


class ArchiveSafety(unittest.TestCase):
    def archive(self, root, entries):
        path = root / 'input.tar'
        with tarfile.open(path, 'w') as tf:
            for name, kind in entries:
                m = tarfile.TarInfo(name)
                m.type = kind
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    m.linkname = '/tmp/escape'
                if kind == tarfile.REGTYPE:
                    m.size = 2
                    tf.addfile(m, io.BytesIO(b'ok'))
                else:
                    tf.addfile(m)
        return path

    def test_rejects_traversal_absolute_links_devices_and_duplicates(self):
        for entries in [[('../escape', tarfile.REGTYPE)], [('/escape', tarfile.REGTYPE)], [('link', tarfile.SYMTYPE)], [('hard', tarfile.LNKTYPE)], [('device', tarfile.CHRTYPE)], [('same', tarfile.REGTYPE), ('same', tarfile.REGTYPE)]]:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as d:
                root = pathlib.Path(d)
                with self.assertRaises(ValueError):
                    package.extract(self.archive(root, entries), root / 'output')
                self.assertFalse((root / 'output').exists())

    def test_regular_archive_restores_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            package.extract(self.archive(root, [('source/file.txt', tarfile.REGTYPE)]), root / 'output')
            self.assertEqual((root / 'output/source/file.txt').read_bytes(), b'ok')

    def test_alias_duplicates_and_parent_collisions_rejected(self):
        for entries in [[('a/b', tarfile.REGTYPE), ('a/./b', tarfile.REGTYPE)], [('a/b', tarfile.REGTYPE), ('a//b', tarfile.REGTYPE)], [('.', tarfile.DIRTYPE)], [('a/b', tarfile.REGTYPE), ('a', tarfile.REGTYPE)]]:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as d:
                root = pathlib.Path(d)
                with self.assertRaises(ValueError):
                    package.extract(self.archive(root, entries), root / 'output')

    def test_substituted_deployment_contract_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            folder = root / 'deploy/hk-staging'
            folder.mkdir(parents=True)
            for name in package.CONTRACT_BLOBS:
                (folder / name).write_text('substitution')
            with self.assertRaisesRegex(ValueError, 'deployment contract mismatch'):
                package.check_contract(root)

    def test_wrong_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'fake').write_text('not canonical')
            with self.assertRaises(ValueError):
                package.fingerprint(root)

    def test_corrupt_package_rejected_before_docker(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'runtime-package.tar.gz').write_bytes(b'corrupt')
            (root / 'runtime-package.sha256').write_text('0' * 64 + '  runtime-package.tar.gz\n')
            with patch.object(package.subprocess, 'run') as docker:
                with self.assertRaises(ValueError):
                    package.restore(root)
                docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
