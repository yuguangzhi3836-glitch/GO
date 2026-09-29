from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from write_sha256s import write_sha256s


class EvidenceWriterHygieneTest(unittest.TestCase):
    def test_manifest_excludes_itself_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            (root / "b.txt").write_bytes(b"beta\n")
            (root / "nested" / "a.json").write_bytes(b'{"ok":true}\n')
            output = root / "SHA256SUMS"
            output.write_text("stale self-referential content\n")

            write_sha256s(root, output)
            first = output.read_bytes()
            write_sha256s(root, output)
            second = output.read_bytes()

            self.assertEqual(first, second)
            lines = first.decode().splitlines()
            self.assertEqual(
                [line.split("  ", 1)[1] for line in lines],
                ["b.txt", "nested/a.json"],
            )
            expected = {
                "b.txt": hashlib.sha256(b"beta\n").hexdigest(),
                "nested/a.json": hashlib.sha256(b'{"ok":true}\n').hexdigest(),
            }
            self.assertEqual(
                {path: digest for digest, path in (line.split("  ", 1) for line in lines)},
                expected,
            )
            self.assertNotIn("SHA256SUMS", first.decode())

    def test_output_must_be_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "inside evidence root"):
                write_sha256s(root, Path(directory) / "outside.txt")


if __name__ == "__main__":
    unittest.main()
