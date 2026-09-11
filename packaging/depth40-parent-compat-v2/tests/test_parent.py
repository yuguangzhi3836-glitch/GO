import hashlib
import json
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import io
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_parent import files, sha, verify_sums, safe_extract, source_identity, image_identity, restore


class ParentGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / 'package'; self.package.mkdir()
        (self.package / 'a.txt').write_bytes(b'fixed source\n')
        self.seal()

    def seal(self):
        (self.package / 'SHA256SUMS').write_text(''.join(
            sha(path) + '  ' + name + '\n' for name, path in files(self.package).items()
            if name != 'SHA256SUMS'))

    def test_missing_file_rejected(self):
        (self.package / 'a.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'FILE_SET_MISMATCH'): verify_sums(self.package)

    def test_extra_file_rejected(self):
        (self.package / 'extra').write_text('x')
        with self.assertRaisesRegex(ValueError, 'FILE_SET_MISMATCH'): verify_sums(self.package)

    def test_altered_bytes_rejected(self):
        (self.package / 'a.txt').write_bytes(b'wrong source\n')
        with self.assertRaisesRegex(ValueError, 'FILE_HASH_MISMATCH'): verify_sums(self.package)

    def test_nested_checksum_file_is_covered(self):
        sub = self.package / 'runtime'; sub.mkdir()
        (sub / 'SHA256SUMS').write_text('original nested sums')
        self.seal()
        (sub / 'SHA256SUMS').write_text('rewritten nested sums')
        with self.assertRaisesRegex(ValueError, 'FILE_HASH_MISMATCH'): verify_sums(self.package)

    def test_duplicate_checksums_rejected(self):
        f = self.package / 'SHA256SUMS'; f.write_text(f.read_text() * 2)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_CHECKSUM'): verify_sums(self.package)

    def test_symbolic_link_rejected(self):
        (self.package / 'linked').symlink_to(self.package / 'a.txt')
        with self.assertRaisesRegex(ValueError, 'SYMLINK_NOT_ALLOWED'): verify_sums(self.package)

    def test_archive_traversal_rejected_without_extraction(self):
        archive = self.root / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as z: z.writestr('../escape', 'x')
        with self.assertRaisesRegex(ValueError, 'UNSAFE_PATH'):
            safe_extract(archive, self.root / 'out')
        self.assertFalse((self.root / 'out').exists())
        self.assertFalse((self.root / 'escape').exists())

    def test_archive_symlink_rejected(self):
        archive = self.root / 'bad.zip'
        entry = zipfile.ZipInfo('link'); entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, 'w') as z: z.writestr(entry, '../elsewhere')
        with self.assertRaisesRegex(ValueError, 'UNSAFE_ARCHIVE_TYPE'):
            safe_extract(archive, self.root / 'out')

    def test_duplicate_archive_member_rejected(self):
        archive = self.root / 'duplicate.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('a', 'one')
            with self.assertWarns(UserWarning): z.writestr('a', 'two')
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_ARCHIVE_MEMBER'):
            safe_extract(archive, self.root / 'out')

    def test_restore_refuses_existing_empty_destination(self):
        target = self.root / 'existing'; target.mkdir()
        with self.assertRaisesRegex(ValueError, 'RESTORE_TARGET_EXISTS'):
            restore(self.package, target, lambda p: {'checksummed': verify_sums(p)})
        self.assertEqual(list(target.iterdir()), [])

    def test_restore_refuses_destination_inside_source(self):
        with self.assertRaisesRegex(ValueError, 'RESTORE_INSIDE_SOURCE'):
            restore(self.package, self.package / 'nested', lambda p: {'checksummed': verify_sums(p)})

    def test_restore_copies_and_rechecks_bytes(self):
        target = self.root / 'new'
        result = restore(self.package, target, lambda p: {'checksummed': verify_sums(p)})
        self.assertEqual(result['restore_roundtrip'], 'PASS')
        self.assertEqual((target / 'a.txt').read_bytes(), b'fixed source\n')
        self.assertEqual(verify_sums(target), 1)

    def test_source_tree_orders_full_paths_lexically(self):
        source = self.root / 'source'; source.mkdir()
        (source / 'a').mkdir(); (source / 'a/x').write_text('x')
        (source / 'a.txt').write_text('a')
        raw = ('a.txt\0' + sha(source / 'a.txt') + '\n' + 'a/x\0' + sha(source / 'a/x') + '\n').encode()
        self.assertEqual(source_identity(source), {'source_files': 2, 'source_tree_sha256': hashlib.sha256(raw).hexdigest()})

    def test_image_config_id_uses_config_bytes(self):
        config = b'{"architecture":"amd64","os":"linux"}'
        tag = 'go-fixture:fixed'
        manifest = json.dumps([{'Config': 'blobs/sha256/config', 'RepoTags': [tag], 'Layers': []}]).encode()
        archive = self.root / 'image.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for name, content in [('manifest.json', manifest), ('blobs/sha256/config', config)]:
                info = tarfile.TarInfo(name); info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        pins = {'image_archive_bytes': archive.stat().st_size, 'image_archive_sha256': sha(archive),
                'image_tag': tag, 'image_config_id': 'sha256:' + hashlib.sha256(config).hexdigest()}
        self.assertEqual(image_identity(archive, pins), pins['image_config_id'])
        pins['image_config_id'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'IMAGE_CONFIG_ID_MISMATCH'): image_identity(archive, pins)


if __name__ == '__main__': unittest.main()
