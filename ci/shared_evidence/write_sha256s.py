#!/usr/bin/env python3
"""Write a deterministic SHA256SUMS manifest without self-reference."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import tempfile


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_sha256s(root: Path, output: Path) -> None:
    root = root.resolve()
    output = output.resolve()
    try:
        output_rel = output.relative_to(root)
    except ValueError as exc:
        raise ValueError("output must be inside evidence root") from exc

    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.resolve() != output
    )
    lines = [
        f"{_digest(path)}  {path.relative_to(root).as_posix()}\n"
        for path in files
    ]

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.writelines(lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    if output_rel.as_posix() in {
        line.split("  ", 1)[1].rstrip("\n") for line in lines
    }:
        raise AssertionError("checksum manifest must not contain itself")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_sha256s(args.root, args.output)


if __name__ == "__main__":
    main()
