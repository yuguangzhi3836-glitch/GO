#!/bin/sh
set -eu

commit=${1:?exact commit required}
candidate=control-plane/boss-test-pr-live-integration-v1
repo=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cd "$repo"
git -c core.autocrlf=false -c core.eol=lf archive --format=tar "$commit" "$candidate" |
  tar -C "$work" -xf -

root="$work/$candidate"
test "$(perl -0777 -ne 'print tr/\r/\r/' "$root/SHA256SUMS")" = 0
(
  cd "$root"
  sha256sum -c SHA256SUMS
)
