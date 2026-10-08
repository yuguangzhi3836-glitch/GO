import io
import tempfile
import unittest
from pathlib import Path

import line_endings


class LineEndingReportTests(unittest.TestCase):
    def run_report(self, root: Path) -> list[str]:
        output = io.StringIO()
        result = line_endings.main([str(root)], stdout=output)
        self.assertEqual(result, 0)
        return output.getvalue().splitlines()

    def test_reports_required_line_ending_cases_and_skips_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lf.txt").write_bytes(b"one\ntwo\n")
            (root / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
            (root / "mixed.txt").write_bytes(b"one\nline\r\n")
            (root / "cr.txt").write_bytes(b"one\rtwo\r")
            (root / "empty.txt").write_bytes(b"")
            (root / "no_trailing_newline.txt").write_bytes(b"just text")

            nested = root / "nested"
            nested.mkdir()
            (nested / "also_lf.txt").write_bytes(b"a\nb\nc\n")

            git_dir = nested / ".git"
            git_dir.mkdir()
            (git_dir / "ignored.txt").write_bytes(b"skip\r\nme\r\n")

            lines = self.run_report(root)

            self.assertEqual(
                lines,
                [
                    "CR\tcrlf=0\tlf=0\tcr=2\tcr.txt",
                    "CRLF\tcrlf=2\tlf=0\tcr=0\tcrlf.txt",
                    "NONE\tcrlf=0\tlf=0\tcr=0\tempty.txt",
                    "LF\tcrlf=0\tlf=2\tcr=0\tlf.txt",
                    "MIXED\tcrlf=1\tlf=1\tcr=0\tmixed.txt",
                    "LF\tcrlf=0\tlf=3\tcr=0\tnested/also_lf.txt",
                    "NONE\tcrlf=0\tlf=0\tcr=0\tno_trailing_newline.txt",
                    "TOTAL\tfiles=7\tmixed=1",
                ],
            )

    def test_binary_file_is_reported_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "binary.bin").write_bytes(b"\x00\x01\r\n\x02")

            lines = self.run_report(root)

            self.assertEqual(
                lines,
                [
                    "NONE\tcrlf=0\tlf=0\tcr=0\tbinary.bin",
                    "TOTAL\tfiles=1\tmixed=0",
                ],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
