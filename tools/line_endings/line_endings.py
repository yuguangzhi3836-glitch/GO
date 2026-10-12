#!/usr/bin/env python3
"""Report line-ending statistics for files in a directory tree."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO


@dataclass(frozen=True)
class FileStats:
    path: str
    classification: str
    crlf: int
    lf: int
    cr: int


def count_line_endings(data: bytes) -> tuple[int, int, int]:
    crlf = 0
    lf = 0
    cr = 0
    index = 0
    length = len(data)

    while index < length:
        byte = data[index]
        if byte == 13:
            if index + 1 < length and data[index + 1] == 10:
                crlf += 1
                index += 2
                continue
            cr += 1
        elif byte == 10:
            lf += 1
        index += 1

    return crlf, lf, cr


def classify_line_endings(crlf: int, lf: int, cr: int) -> str:
    kinds = sum(1 for value in (crlf, lf, cr) if value)
    if kinds == 0:
        return "NONE"
    if kinds > 1:
        return "MIXED"
    if crlf:
        return "CRLF"
    if lf:
        return "LF"
    return "CR"


def inspect_file(path: Path) -> FileStats:
    try:
        path_stat = path.stat(follow_symlinks=False)
    except OSError:
        return FileStats(str(path), "NONE", 0, 0, 0)

    if not stat.S_ISREG(path_stat.st_mode):
        return FileStats(str(path), "NONE", 0, 0, 0)

    try:
        data = path.read_bytes()
    except OSError:
        return FileStats(str(path), "NONE", 0, 0, 0)

    if b"\x00" in data:
        return FileStats(str(path), "NONE", 0, 0, 0)

    crlf, lf, cr = count_line_endings(data)
    return FileStats(str(path), classify_line_endings(crlf, lf, cr), crlf, lf, cr)


def walk_directory(root: Path) -> Iterable[FileStats]:
    records: list[FileStats] = []

    for current_root, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        current_path = Path(current_root)
        for name in filenames:
            file_path = current_path / name
            try:
                if file_path.is_symlink():
                    continue
            except OSError:
                pass
            stats = inspect_file(file_path)
            records.append(
                FileStats(
                    path=file_path.relative_to(root).as_posix(),
                    classification=stats.classification,
                    crlf=stats.crlf,
                    lf=stats.lf,
                    cr=stats.cr,
                )
            )

    return sorted(records, key=lambda record: record.path)


def write_report(root: Path, stdout: TextIO) -> int:
    records = list(walk_directory(root))
    mixed = 0

    for record in records:
        if record.classification == "MIXED":
            mixed += 1
        stdout.write(
            f"{record.classification}\tcrlf={record.crlf}\tlf={record.lf}\tcr={record.cr}\t{record.path}\n"
        )

    stdout.write(f"TOTAL\tfiles={len(records)}\tmixed={mixed}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Directory to scan recursively")
    return parser


def main(argv: list[str] | None = None, stdout: TextIO | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.directory)
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    return write_report(root, stdout or sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
