import io
import pathlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import seal


class Safety(unittest.TestCase):
    def archive(self, root, entries):
        path = root / 'input.tar'
        with tarfile.open(path, 'w') as tf:
            for name, kind, link in entries:
                m = tarfile.TarInfo(name)
                m.type = kind
                m.linkname = link
                m.mode = 0o755
                if m.isfile():
                    m.size = 2
                    tf.addfile(m, io.BytesIO(b'ok'))
                else:
                    tf.addfile(m)
        return path

    def test_valid_node_relative_link_restores(self):
        entries = [('node/lib/npm.js', tarfile.REGTYPE, ''), ('node/bin/npm', tarfile.SYMTYPE, '../lib/npm.js')]
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            seal.extract(self.archive(root, entries), root / 'out')
            self.assertEqual((root / 'out/node/bin/npm').read_bytes(), b'ok')
            self.assertTrue((root / 'out/node/bin/npm').is_symlink())

    def test_unsafe_paths_and_types_rejected(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE), ('.', tarfile.DIRTYPE), ('device', tarfile.CHRTYPE), ('hard', tarfile.LNKTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                root = pathlib.Path(d)
                with self.assertRaises(ValueError):
                    seal.extract(self.archive(root, [(name, kind, '')]), root / 'out')
                self.assertFalse((root / 'out').exists())

    def test_alias_duplicates_and_file_parents_rejected(self):
        for extra in ['a/./b', 'a//b', 'a']:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as d:
                root = pathlib.Path(d)
                entries = [('a/b', tarfile.REGTYPE, ''), (extra, tarfile.REGTYPE, '')]
                with self.assertRaises(ValueError):
                    seal.extract(self.archive(root, entries), root / 'out')

    def test_escaping_dangling_chained_and_parent_links_rejected(self):
        cases = [
            [('node/link', tarfile.SYMTYPE, '../../escape')],
            [('node/link', tarfile.SYMTYPE, '/absolute')],
            [('node/link', tarfile.SYMTYPE, 'missing')],
            [('a', tarfile.SYMTYPE, 'b'), ('b', tarfile.SYMTYPE, 'a')],
            [('target', tarfile.REGTYPE, ''), ('a', tarfile.SYMTYPE, 'target'), ('a/file', tarfile.REGTYPE, '')],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as d:
                root = pathlib.Path(d)
                with self.assertRaises(ValueError):
                    seal.extract(self.archive(root, entries), root / 'out')

    def test_existing_destination_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            out = root / 'out'
            out.mkdir()
            (out / 'keep').write_text('original')
            with self.assertRaises(ValueError):
                seal.extract(self.archive(root, [('keep', tarfile.REGTYPE, '')]), out)
            self.assertEqual((out / 'keep').read_text(), 'original')

    def test_corrupt_package_rejected_before_commands(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'node-seal.tar.gz').write_bytes(b'corrupt')
            (root / 'node-seal.sha256').write_text('0' * 64)
            with patch.object(seal.subprocess, 'run') as command:
                with self.assertRaises(ValueError):
                    seal.restore(root)
                command.assert_not_called()

    def test_noncanonical_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'fake').write_text('fake')
            with self.assertRaises(ValueError):
                seal.fingerprint(root)


if __name__ == '__main__':
    unittest.main()
