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
a builder version the signed TEST_PR result does not corroborate
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
builder claim uncorroborated           REJECT  candidate_test_result_evidence_builder_version
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
signed TEST_PR Evidence `go-boss-test-pr-52-0342850d8822` supplied the artifact
digest, the test identity and the sealed package, the staged builder supplied the
build definition, the live runtime supplied the rollback target, and the live deploy
contract supplied the service topology. The two earlier results for the same source
(`…-0673b27f427c` and `…-83b0e20f3980`) stay in the evidence repository and in
`release_candidate_reconciliation_history`: they are what this candidate's lineage was
built on, and rewriting them to match the present would falsify the past.

`test_result_identity.evidence_id` names that Evidence's own record on the evidence
repository -- the commit, or a record id where the record is not a commit. It is
never the blob id, and never a digest of the evidence file: the field has meant a
record identity since it was defined, so a reconciliation that recorded bytes
instead would change the meaning without changing the name.

Two of those values are not independent claims, and admission now says so. The
`signed TEST_PR result` is the only thing that can corroborate the artifact **and**
the builder that produced it, so the declared `executor_version` must be the version
the result itself reports. An artifact id names an image, not the executor that made
it; without the binding, an artifact built by a newer executor could be described as
the work of an older one and still be admitted.

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

## One candidate identity, and the digest over it

`go.release-candidate.v1` is the **only** candidate identity in the converged
baseline. The Hong Kong media-topology line carried a second one
(`go.hk-candidate-contract.v1/v2/v3`); those documents are now **read-only history**
and are retired at T10. This component owns both the converged fact and the reader
for the legacy one, so there is exactly one place where "what is this candidate"
is answered.

`candidate_fact.py` is the single implementation of the cross-component candidate
digest:

```text
candidate_contract_sha256 = sha256(canonical_json(RELEASE_CANDIDATE_V1_CONVERGED))
canonical_json = json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode("utf-8")
```

The digest covers the candidate facts and **nothing else**. It deliberately does
not cover a rehearsal body, a rehearsal checksum, a topology implementation hash,
a launcher module hash, a runtime pin, an execution window or a deployment mode --
those either belong to the plan, to a capability, or to the installation facts.

Consequences worth stating plainly:

* the same candidate digests the same however its JSON is key-ordered, indented or
  spaced, and differently as soon as any candidate fact changes;
* a candidate that declares the prohibited migration condition has **no** converged
  form, so it has no digest and admits nothing;
* `migration_required` is a **PROHIBITED_CONDITION_DECLARATION**, pinned to `false`
  in the contract. V1 does not execute database migrations. It is stated rather
  than omitted so that "no migration" is a declaration instead of a missing field.
* the admission document reports the digest as `candidate_contract_sha256`, and
  reports `null` when the candidate was refused -- `null` means "no such identity
  exists", never "unknown but probably fine".

## Reading the legacy contract

`legacy_candidate_contract.py` is marked `LEGACY READ ONLY / DO NOT WRITE /
RETIRE AT T10`. It validates the three legacy shapes, produces an explicit
`LEGACY_CANDIDATE_VIEW`, and keeps that view's non-candidate fields -- rehearsal,
topology, revisions, environment, profile -- out of the converged fact.

Its mapping table is explicit and tested. Where a legacy field has no loss-free
destination the gap is **named**, not papered over: `LEGACY_MAPPING_GAPS` records
six identities a converged candidate must state that no legacy document can
supply, including `source_fingerprint` -- the legacy `source_tree_sha256` has the
same shape but a different definition, so mapping it would silently redefine the
identity admission checks. A legacy view is therefore never promotable, and a
legacy digest can never be compared against a converged one: the two are
different kinds, and `verify_task_candidate_digest` refuses the legacy kind by
name.

## What it deliberately does not do

* No rollback eligibility beyond naming the previous known-good target (#104).
* No supply-chain framework: V1 needs enough to support the current HK-STAGING E2E
  and no more.
* No business acceptance: whether the release gates PASS is the operator's signed
  declaration on the deploy plan, not something re-derived here.
