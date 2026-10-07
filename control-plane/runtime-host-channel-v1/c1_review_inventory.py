"""Explicit review inventory: data-only, bounded, resolved at the frozen candidate.

This is scope selection for a new review, NOT a C13 supplement/retry API. The
Issue/SHA round identity is unchanged; editing scope cannot purchase another run.
"""
from __future__ import annotations

import re

from c1_execution_contract import MAX_MACHINE_INVENTORY, MAX_REVIEW_TEST_FILES, Refused

MARKER = "machine inventory:"
TOKEN = re.compile(
    r"(?:application/tests/(?:[A-Za-z0-9_-]+/){0,8}"
    r"|control-plane/boss-test-pr-live-integration-v1/tests/)test_[A-Za-z0-9_-]+\.py"
    r"(?:::[A-Za-z_][A-Za-z0-9_]*){0,2}\Z"
)


def explicit_inventory(body):
    """Accept exactly one explicit field; never mine prose or comment instructions."""
    values = []
    for line in body.splitlines():
        line = line.strip().lstrip("-*+").strip()
        if line.lower().startswith(MARKER):
            values.append(line[len(MARKER):].strip())
    if not values:
        return None
    if len(values) != 1:
        raise Refused("REVIEW_INVENTORY_AMBIGUOUS")
    raw = values[0]
    if not raw or len(raw) > MAX_MACHINE_INVENTORY:
        raise Refused("REVIEW_INVENTORY_EMPTY_OR_TOO_LONG")
    paths = raw.split()
    if len(paths) > MAX_REVIEW_TEST_FILES or len(paths) != len(set(paths)):
        raise Refused("REVIEW_INVENTORY_DUPLICATE_OR_TOO_MANY")
    if any(not TOKEN.fullmatch(path) for path in paths):
        raise Refused("REVIEW_INVENTORY_UNSAFE_PATH")
    # Preserve ordering. A caller must see the exact inventory they commissioned.
    return " ".join(paths)


def require_frozen_inventory(reader, application_tree, inventory, *, candidate_sha=None):
    """Require regular test files in the frozen application or candidate root tree.

    Pytest owns node collection; this verifies file provenance, not whether a
    class/function exists. Missing nodes must still fail in the machine job.
    Cache common tree reads and reject symlinks/submodules at every component.
    """
    cache = {}
    root_tree = None
    for token in inventory.split():
        parts = token.split("::", 1)[0].split("/")
        if parts[0] == "application":
            parts = parts[1:]
            tree = application_tree
        else:
            # Control-plane bytes belong to the exact candidate ROOT, never main
            # or the execution backend's application tree.
            if not isinstance(candidate_sha, str) or not re.fullmatch("[0-9a-f]{40}", candidate_sha):
                raise Refused("REVIEW_INVENTORY_CANDIDATE_SHA_REQUIRED")
            if root_tree is None:
                root_tree = reader.read_commit_tree(candidate_sha)
                if not isinstance(root_tree, str) or not re.fullmatch("[0-9a-f]{40}", root_tree):
                    raise Refused("REVIEW_INVENTORY_TREE_SHA_INVALID")
            tree = root_tree
        for index, part in enumerate(parts):
            if tree not in cache:
                cache[tree] = reader.read_tree(tree)
            matches = [entry for entry in cache[tree] if entry.get("path") == part]
            if len(matches) != 1:
                raise Refused("REVIEW_INVENTORY_FILE_NOT_IN_FROZEN_TREE")
            entry = matches[0]
            last = index == len(parts) - 1
            if last:
                if entry.get("type") != "blob" or entry.get("mode") not in ("100644", "100755"):
                    raise Refused("REVIEW_INVENTORY_NOT_A_REGULAR_FILE")
            elif entry.get("type") != "tree" or entry.get("mode") != "040000":
                raise Refused("REVIEW_INVENTORY_NOT_A_REGULAR_DIRECTORY")
            tree = entry.get("sha")
            if not isinstance(tree, str) or not re.fullmatch("[0-9a-f]{40}", tree):
                raise Refused("REVIEW_INVENTORY_TREE_SHA_INVALID")
