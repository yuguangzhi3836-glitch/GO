#!/bin/sh
# Produce the canonical provenance proof for a source identity (CCV1-88 / WP-6).
#
#   verify-canonical-source.sh <repository> <source-commit> <out-dir> [source-tree] [runtime-dir]
#
# Run this where the repository is -- a workstation or a CI runner -- and hand the resulting
# verdict to `install-hk-executor-facts.sh`, which cannot reach a repository itself.
#
# What it proves, and nothing more:
#
#   1  <source-commit> is a commit of this repository, and it is on the ancestor chain of
#      `origin/main` (override with GO_CANONICAL_REF)
#   2  <source-tree> is that commit's own tree object
#   5  every runtime module in <runtime-dir> hashes to the blob that commit holds at
#      hk-staging/source/executor/runtime/<name>.py
#
# The verifier never fetches, so `origin/main` must already be current in the clone you point
# it at. Which commit was proved against is recorded in the verdict as `canonical_commit`, so
# a stale reference is a visible fact rather than an invisible one.
#
# Exit codes: 0 the proof holds; 3 the proof refused (the reason and the file list are in the
# verdict document); 2 the request could not be answered (unreadable input, wrong contract).
set -eu

repository=${1:?repository path required}
source_commit=${2:?source commit required (40-hex)}
out_dir=${3:?output directory required}
source_tree=${4:-}
runtime_dir=${5:-}

repo_relative=$(CDPATH= cd -- "$repository" && pwd)

# The tree object is derived, not asked for: `git rev-parse --verify <commit>^{tree}` is the
# only tree a fact may record, and taking it from the caller would let the two disagree.
if [ -z "$source_tree" ]; then
  source_tree=$(git -C "$repo_relative" rev-parse --verify --quiet "$source_commit^{tree}")
fi
if [ -z "$runtime_dir" ]; then
  runtime_dir="$repo_relative/hk-staging/source/executor/runtime"
fi

test -n "$source_tree"
test -d "$runtime_dir"

python3 "$repo_relative/control-plane/command-center-canonical-provenance-v1/command-center/go-canonical-provenance" \
  install-source \
  --repository "$repo_relative" \
  --canonical-ref "${GO_CANONICAL_REF:-origin/main}" \
  --source-commit "$source_commit" \
  --source-tree "$source_tree" \
  --runtime-dir "$runtime_dir" \
  --out "$out_dir" \
  --expect PASS

echo "CANONICAL_PROOF: $out_dir/CANONICAL_PROVENANCE.json"
echo "source_commit=$source_commit source_tree=$source_tree"
