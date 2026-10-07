"""Validate the frozen whitespace-delimited inventory; emit NUL-delimited argv.

Run by the trusted backend before Docker. Never imports candidate code.
The container receives absolute paths, while its cwd is application/ so that
the candidate's tests helper package is importable.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import sys


def inventory_paths(value: str, candidate: Path) -> list[str]:
    if not value or len(value) > 16384:
        raise ValueError("INVALID_MACHINE_INVENTORY")
    tokens = value.split()
    if not tokens or len(tokens) > 128:
        raise ValueError("INVALID_MACHINE_INVENTORY")
    root = candidate.resolve(strict=True)
    result = []
    for token in tokens:
        parts = token.split("::")
        path_text, selectors = parts[0], parts[1:]
        path = PurePosixPath(path_text)
        control_test = bool(re.fullmatch(
            r"control-plane/boss-test-pr-live-integration-v1/tests/test_[A-Za-z0-9_-]+\.py",
            path_text))
        boundary = (root / "control-plane/boss-test-pr-live-integration-v1/tests"
                    if control_test else root / "application/tests")
        if boundary.is_symlink() or not boundary.is_dir():
            raise ValueError("INVALID_TEST_ROOT")
        if (len(parts) > 3
                or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", selector)
                       for selector in selectors)
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", path_text)
                or path_text != path.as_posix()
                or ".." in path.parts
                or (path.parts[:2] != ("application", "tests") and not control_test)):
            raise ValueError("INVALID_TEST_PATH")
        # Reject every symlink component, including application/, even if the
        # target currently happens to stay inside the checkout.
        current = root
        for part in path.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("SYMLINK_TEST_PATH")
        target = current.resolve(strict=True)
        if not target.is_relative_to(boundary.resolve(strict=True)):
            raise ValueError("TEST_PATH_OUTSIDE_INVENTORY")
        if not target.is_dir() and not (target.is_file() and target.suffix == ".py"):
            raise ValueError("INVALID_TEST_FILE")
        # Keep an accepted pytest node id as one literal argv. Filesystem checks above
        # apply only to its path; selectors never participate in path resolution.
        result.append("/srv/" + token)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    try:
        paths = inventory_paths(os.environ.get("MACHINE_INVENTORY", ""), args.candidate)
    except (ValueError, OSError):
        # Input may be malicious: do not echo it into logs or workflow commands.
        print("MACHINE_INVENTORY_REJECTED", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(b"".join(p.encode("utf-8") + b"\0" for p in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
