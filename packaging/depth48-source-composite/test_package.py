"""Synthetic packaging checks only; these are not DEPTH48 application acceptance."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from create_archive import create, verify_zip
from verify_parent import inventory, safe_name, sha256, verify


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'synthetic-parent'
        self.root.mkdir()
        (self.root / 'source/application').mkdir(parents=True)
        (self.root / 'source/application/run.sh').write_bytes(b'#!/bin/sh\nexit 0\n')
        (self.root / 'source/application/run.sh').chmod(0o755)
        (self.root / 'source/application/picture.bin').write_bytes(bytes(range(256)))
        f = {n: r['sha256'] for n, r in inventory(self.root / 'source/application')[0].items()}
        write_json(self.root / 'source/fingerprint.json', f)
        (self.root / 'previous_parent').mkdir()
        payload = b'synthetic fixture, not a real runtime or original browser evidence'
        part = self.root / 'previous_parent/old.zip.part000'
        part.write_bytes(payload)
        row = inventory(part.parent)[0][part.name]
        write_json(part.parent / 'PARENT_PARTS.json', {
            'zip_file': 'old.zip', 'zip_bytes': len(payload), 'zip_sha256': sha256(part),
            'parts': [dict(row, name=part.name)]})
        for name in ('README.md', 'verify_parent.py', 'create_archive.py'):
            (self.root / name).write_text('Synthetic test fixture only\n')
        self.manifest = {
            'schema': 'go.source-composite-parent.v1', 'name': self.root.name,
            'package_kind': 'SOURCE_COMPOSITE_CANDIDATE',
            'new_runtime': {'status': 'NOT_BUILT'}, 'gates': {'FINAL_RELEASE': 'HOLD'},
            'application': {'git_tree': inventory(self.root / 'source/application')[1]['.'],
                'files': len(f), 'fingerprint_path': 'fingerprint.json',
                'source_tree_sha256': hashlib.sha256(''.join(f'{p}\0{h}\n' for p, h in
                    sorted(f.items())).encode()).hexdigest()},
            'previous_parent': {'zip_bytes': len(payload), 'zip_sha256': sha256(part), 'parts': 1}}
        self.seal()

    def seal(self):
        self.manifest['metadata_sha256'] = {n: sha256(self.root / n) for n in
            ('README.md', 'verify_parent.py', 'create_archive.py')}
        self.manifest['payloads'] = {}
        for folder in ('source', 'previous_parent'):
            rows, trees = inventory(self.root / folder)
            self.manifest['payloads'][folder] = {'git_tree': trees['.'], 'files': len(rows),
                                                'bytes': sum(r['bytes'] for r in rows.values())}
        write_json(self.root / 'PARENT_MANIFEST.json', self.manifest)
        self.digest = sha256(self.root / 'PARENT_MANIFEST.json')
        sums = dict(self.manifest['metadata_sha256'], **{'PARENT_MANIFEST.json': self.digest})
        (self.root / 'MANIFEST.sha256').write_text(''.join(f'{h}  {n}\n' for n, h in sorted(sums.items())))

    def test_hash_matches_native_git_with_binary_and_executable(self):
        clone = Path(self.tmp.name) / 'git-fixture'
        shutil.copytree(self.root / 'source', clone)
        expected = inventory(clone)[1]['.']
        for cmd in (['git', 'init', '-q'], ['git', '-c', 'core.autocrlf=false', 'add', '-f', '.']):
            subprocess.run(cmd, cwd=clone, check=True, capture_output=True)
        actual = subprocess.check_output(['git', 'write-tree'], cwd=clone, text=True).strip()
        self.assertEqual(actual, expected)

    def test_roundtrip_and_reproducibility(self):
        self.assertEqual(verify(self.root, self.digest)['source_composite_integrity'], 'PASS')
        first, second = Path(self.tmp.name) / 'one.zip', Path(self.tmp.name) / 'two.zip'
        create(self.root, first, self.digest)
        create(self.root, second, self.digest)
        self.assertEqual(sha256(first), sha256(second))
        restored = Path(self.tmp.name) / 'restored'
        with zipfile.ZipFile(first) as z:
            # Only this locally created and already validated fixture is extracted.
            z.extractall(restored)
            for info in z.infolist():
                (restored / info.filename).chmod(0o755 if info.external_attr >> 16 & 0o111 else 0o644)
        self.assertEqual(verify(restored / self.root.name, self.digest), verify(self.root, self.digest))

    def test_source_tamper_and_mode_detected(self):
        p = self.root / 'source/application/run.sh'
        p.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'PAYLOAD_GIT_TREE'):
            verify(self.root, self.digest)
        p.chmod(0o755)
        p.write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'PAYLOAD_GIT_TREE'):
            verify(self.root, self.digest)

    def test_missing_part_and_extra_file_detected(self):
        part = self.root / 'previous_parent/old.zip.part000'
        saved = part.read_bytes()
        part.unlink()
        with self.assertRaisesRegex(ValueError, 'PAYLOAD_GIT_TREE'):
            verify(self.root, self.digest)
        part.write_bytes(saved)
        (self.root / 'extra').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'ROOT_FILE_SET'):
            verify(self.root, self.digest)

    def test_part_sha_checked_independently(self):
        (self.root / 'previous_parent/old.zip.part000').write_bytes(b'tampered')
        self.seal()  # Even with a rebound Git tree, the original part binding must fail.
        with self.assertRaisesRegex(ValueError, 'PART_'):
            verify(self.root, self.digest)

    def test_link_and_unsafe_path_rejected(self):
        (self.root / 'source/link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'SPECIAL_FILE'):
            verify(self.root, self.digest)
        for name in ('../escape', '/absolute', 'a//b', 'a/./b', 'a\\b', 'C:/file', 'a\nb'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'UNSAFE_NAME'):
                safe_name(name)

    def test_existing_output_and_manifest_tamper_rejected(self):
        out = Path(self.tmp.name) / 'keep.zip'
        out.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
            create(self.root, out, self.digest)
        self.assertEqual(out.read_bytes(), b'keep')
        with self.assertRaisesRegex(ValueError, 'EXTERNAL_MANIFEST_SHA256'):
            verify(self.root, '0' * 64)

    def test_bad_zip_members_rejected(self):
        out = Path(self.tmp.name) / 'bad.zip'
        rows, _ = inventory(self.root)
        for attack in ('traversal', 'duplicate', 'symlink'):
            with self.subTest(attack=attack):
                with zipfile.ZipFile(out, 'w') as z:
                    if attack == 'traversal':
                        z.writestr('../outside', b'x')
                    else:
                        for name, row in rows.items():
                            info = zipfile.ZipInfo(self.root.name + '/' + name)
                            mode = int(row['mode'], 8)
                            if attack == 'symlink' and name == 'README.md':
                                mode = 0o120777
                            info.external_attr = mode << 16
                            z.writestr(info, (self.root / name).read_bytes())
                        if attack == 'duplicate':
                            z.writestr(self.root.name + '/README.md', b'bad')
                with self.assertRaises(ValueError):
                    verify_zip(out, rows, self.root.name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
