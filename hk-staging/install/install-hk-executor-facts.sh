#!/bin/sh
# Install the Hong Kong executor's controlled facts (CCV1-86 / WP-5, gate added by CCV1-88 / WP-6).
#
#   install-hk-executor-facts.sh <staged-root> <signing-key> <installer-identity> <candidate-dir> <canonical-proof>
#
# Produces, atomically and root-owned:
#
#   /etc/go-hk-deployctl/candidates-v1/<candidate_contract_sha256>.json
#   /etc/go-hk-deployctl/environment-graph-v1.json
#   /etc/go-hk-deployctl/keys/install-fact-signing.pub
#   /etc/go-hk-deployctl/install-fact-v1.json
#
# and archives the previous fact as install-fact-v1.<old_id>.json.
#
# `<candidate-dir>` holds the approved converged candidate facts, each named after its own
# digest (`<candidate_contract_sha256>.json`); the installer recomputes the digest and
# refuses a file whose name is not its content address, so a directory of hand-named files
# is not a shortcut past admission.
#
# `<canonical-proof>` is the CANONICAL_SOURCE_INVARIANT verdict for this source identity,
# produced where the repository is:
#
#   hk-staging/install/verify-canonical-source.sh <repo> <source-commit> <runtime-dir> <out>
#
# The installer cannot reach a repository, so it consumes that proof and checks it is a PASS
# about *this* commit, *this* tree and *these* module bytes -- recomputing every module hash
# from the files themselves. Without it, nothing is written: not the fact, not the graph, not
# the candidate store, not even the directories they would live in.
#
# STAGED ONLY. This script writes facts; it does not restart a timer, reload systemd, or
# touch a container. Activation is a separately approved operation, and the script says so
# on the way out so that a run cannot be mistaken for one.
#
# ORDER MATTERS. The launcher verifies the installation before it does anything, so a
# launcher that is installed before its fact refuses every action -- including VERIFY.
# Write the facts first, install the launcher last, and read the launcher's own refusal
# if you get it the wrong way round: it names what it could not find.
#
# The signing key is the HK evidence signing private key -- the identity that already
# attests facts this host produces. It is read, never copied, never modified. The canonical
# proof does not add a second signer: it is an input to the install action, not an
# attestation of it.
set -eu

root=${1:?staged candidate root required}
signing_key=${2:?evidence signing private key required}
installer_identity=${3:?installer identity required}
candidate_dir=${4:?directory of approved candidate facts required}
canonical_proof=${5:?canonical provenance proof required (see verify-canonical-source.sh)}

test "$(id -u)" = 0
test -f "$signing_key"
test -d "$candidate_dir"
test -f "$canonical_proof"
test -d "$root/hk-staging/source/executor/runtime"
test -f "$root/hk-staging/source/executor/go-hk-deployctl"
test -f "$root/docs/canonical-baseline/CURRENT_HK_RUNTIME.json"

# The staged tree must be the tree the manifest describes, or the install would hash files
# nobody reviewed. This is the same gate install-hk-agent.sh applies to its own tree.
(
  cd "$root"
  sha256sum -c hk-staging/SOURCE_SHA256SUMS.txt >/dev/null
)

state_dir=${GO_HK_STATE_DIR:-/etc/go-hk-deployctl}

# The install's own source identity: the commit the staged tree came from and the tree
# object of that commit. Recorded in the fact so that "which canonical commit is this"
# stays answerable later. Proving the commit is on `main` used to be deferred to WP-6 and is
# now `--canonical-proof`: the proof is made where the repository is and consumed here, and
# a proof that does not hold means nothing is written.
source_commit=${GO_SOURCE_COMMIT:?GO_SOURCE_COMMIT required (40-hex commit of the staged tree)}
source_tree=${GO_SOURCE_TREE:?GO_SOURCE_TREE required (40-hex tree object of that commit)}

python3 "$root/hk-staging/install/hk_install_facts.py" \
  --state-dir "$state_dir" \
  --runtime-dir "$root/hk-staging/source/executor/runtime" \
  --launcher "$root/hk-staging/source/executor/go-hk-deployctl" \
  --runtime-pointer "$root/docs/canonical-baseline/CURRENT_HK_RUNTIME.json" \
  --source-commit "$source_commit" \
  --source-tree "$source_tree" \
  --canonical-proof "$canonical_proof" \
  --installer-identity "$installer_identity" \
  --signing-key "$signing_key" \
  --candidate-dir "$candidate_dir"

echo "INSTALL_STAGED_ONLY: activation is a separately approved operation"
