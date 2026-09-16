# command-center-candidate-admission-v1

RELEASE_CANDIDATE_V1 admission for the GO Command Center (CC V1-08 / #103).

```text
Command Center defines what is deployable.
```

This component is that definition, and the read-only decision that applies it. It
sits **before** TEST_PR, VERIFY and deploy readiness: a version that cannot
establish its own source, build, artifact, test and rollback identities is refused
here, by name, so the upstream fixes it. Nothing here completes a missing field,
substitutes a branch for a commit, or widens a rule to fit a historical PR.

It is **not** a new live executor deployment gate, and it adds no daemon, timer,
signer, approval authority or gate to the running system: it is an offline,
read-only validator with a CLI, exactly like the deploy readiness evaluator.

## The identity it requires

```text
candidate_id              stable name CANARY / DEPLOY / ROLLBACK can all refer to
source_repository         yuguangzhi3836-glitch/GO, and nothing else
source_commit             one immutable commit a controlled TEST_PR can resolve
application_tree          the application/ git tree at that commit
source_fingerprint        the application source fingerprint at that commit
migration_head            stated always, so "no migration" is a declaration
migration_required        false for every candidate V1 can support
build_definition          profile + Dockerfile + digest + executor version + builder image
artifact_digest           the immutable image the build produced
required_services         the live fixed eight-service topology, exactly
test_result_identity      which signed TEST_PR proves this candidate was built and tested
rollback_relation         the known-good target a rollback would return to
```

The chain those identities form is the point:

```text
immutable GitHub source
        ↓  build definition (the controlled builder, not the caller's choice)
artifact identity
        ↓  the signed TEST_PR result that actually produced it
test identity
        ↓
deployment candidate
```

## Verdicts

```text
ACCEPT    every identity is established and nothing conflicts
REJECT    a rule refuses this candidate; the reason is named
UNKNOWN   an input the decision needs was not supplied -- never rounded up
```

## What is refused

Reused from the live deploy contract wherever a token already means the same
thing; added only where the existing words cannot express the refusal.

```text
candidate schema incomplete or carrying an extra field
source not determinable: a branch, a ref, HEAD, latest, or an abbreviation
source identity that disagrees with the lineage pointer it came from
a build definition that is not the builder actually staged for the executor
a Dockerfile whose digest is not the staged one
artifact digest absent or not an image id
a test result that belongs to another candidate, another commit or another artifact
required_services outside the fixed eight-service topology
rollback relation unknown, or a target that is not an image id
a plan that approves a different candidate, artifact, source or migration
```

The fail-closed rules behind the vocabulary, in the words the tests use:

```text
missing required identity              REJECT  release_candidate_fields
mutable / ambiguous source             REJECT  candidate_source_commit_not_immutable
source fingerprint mismatch            REJECT  source_identity_disagrees_with_the_lineage_pointer
artifact mismatch                      REJECT  candidate_test_result_artifact_digest
test result for another candidate      REJECT  candidate_test_result_source_commit
service boundary violation             REJECT  fixed_topology_required
rollback relation unresolvable         REJECT  candidate_rollback_target_absent
plan/candidate binding conflict        REJECT  plan_candidate_artifact_mismatch
signed TEST_PR Evidence not supplied   UNKNOWN candidate_test_result_evidence_absent
```

## Usage

```text
python go-candidate-admission --candidate <CURRENT_CANDIDATE.json> \
       --test-pr-evidence <signed TEST_PR evidence> \
       [--plan <approved plan bundle>] [--go-repo <GO checkout>] [--out <dir>]
python go-candidate-admission selftest
```

`--go-repo` additionally re-verifies the staged builder's Dockerfile digest from
the checkout, so `build_definition` is a checked fact rather than a claim.
`--candidate` defaults to `docs/canonical-baseline/CURRENT_CANDIDATE.json` inside
`--go-repo`.

Exit code is 0 only for ACCEPT. The document is written to
`<out>/RELEASE_CANDIDATE_ADMISSION.json`, or to stdout when `--out` is omitted.

## The canonical candidate

`docs/canonical-baseline/CURRENT_CANDIDATE.json` carries the
`release_candidate_v1` block for the current candidate. The document's own source
fields remain authoritative for the source identity and the block **must agree
with them**: a candidate that carries two source identities is not one candidate,
and admission refuses it rather than picking one.

Every value in that block is derived from an artifact that already existed -- the
signed TEST_PR Evidence `go-boss-test-pr-52-83b0e20f3980` supplied the artifact
digest and the test identity, the staged builder supplied the build definition, the
live runtime supplied the rollback target, and the live deploy contract supplied
the service topology.

## Authority

```text
is_execution_authority=false  can_create_task=false  can_publish_task=false
can_open_the_request_switch=false  holds_private_key=false  signs_anything=false
accepts_caller_supplied_parameters=false  touches_production=false
is_a_deploy_approval=false    may_read_the_candidate_and_its_evidence=true
```

It never writes, never contacts a host, and never touches Production. Its own
contract refuses any reason token that is not in the contract's vocabulary, so the
component cannot invent a refusal nobody can look up.

## What it deliberately does not do

* No rollback eligibility beyond naming the previous known-good target (#104).
* No supply-chain framework: V1 needs enough to support the current HK-STAGING E2E
  and no more.
* No business acceptance: whether the release gates PASS is the operator's signed
  declaration on the deploy plan, not something re-derived here.
