"""Command line entry point used by the two Lite V2 workflows.

Everything a workflow does to a candidate (freeze it, review it, seal it, verify
it, bind it to the existing ledger) goes through this file, so the logic lives in
reviewable Python instead of inside YAML.

Subcommands
-----------
``spec``          build one frozen candidate spec + contract from the dispatch env, the
                  frozen scope and the candidate's complete pull-request diff
``review``        run one fresh AI review execution (or the labelled local stub)
``seal``          seal a bundle from the contract, the review outcome and machine evidence
``verify``        verify a whole C13+C14 round and write the decision
``bind-ledger``   DRY RUN binding of two execution records onto the existing ledger
``review-brief``  resolve the candidate's own pull request read-only (GitHub's own commit ->
                  pull requests answer), so both cells get the task being graded and not only
                  the change being judged
``rule-input``    resolve the authoritatively declared C14 rule sources from the default
                  branch, or record deterministically why it cannot
``workflow-identity``
                  resolve the blob SHA of the workflow definition that is executing
                  (the other read-only GitHub call)
``raw-evidence``  assemble the non-secret raw review record, so that a refused seal cannot
                  destroy the only copy of the reviewer's reasoning (it never writes a
                  sealed bundle: raw review evidence is not sealed evidence)

No subcommand contacts a database, a credential store or a deployment path. The only three
that touch the network at all are ``review-brief``, ``rule-input`` and ``workflow-identity``,
and all three are read-only GETs made with the token the job already has.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_ai_reviewer  # noqa: E402
import lite_bundle  # noqa: E402
import lite_candidate  # noqa: E402
import lite_canonical  # noqa: E402
import lite_chain  # noqa: E402
import lite_errors  # noqa: E402
import lite_execution_record  # noqa: E402
import lite_ledger_binding  # noqa: E402
import lite_review_brief  # noqa: E402
import lite_rule_input  # noqa: E402

# There used to be DEFAULT_APPLICABLE_RULES / DEFAULT_RULE_VERSION here: three rule-set
# names plus an "unversioned" filler that our own backend invented. They are gone on
# purpose and are not replaced by a different default, because a rule set we made up is
# not evidence about anything - and a record declaring it looks exactly like a record
# declaring real rules (CCV1-145C). The rule set is data now, resolved read-only from the
# default branch's docs/governance/C14_RULE_SOURCES.json by the ``rule-input`` subcommand.

ENV_KEYS = {
    "candidate_sha": "LITE_CANDIDATE_SHA",
    "application_tree": "LITE_APPLICATION_TREE",
    "cell_pair": "LITE_CELL_PAIR",
    "request_id": "LITE_REQUEST_ID",
    "c14_task_id": "LITE_C14_TASK_ID",
    "c13_task_id": "LITE_C13_TASK_ID",
    "ledger_round_id": "LITE_LEDGER_ROUND_ID",
    "nonce": "LITE_NONCE",
    "workflow_identity": "LITE_WORKFLOW_IDENTITY",
    "workflow_sha": "LITE_WORKFLOW_SHA",
    "scope_sha256": "LITE_SCOPE_SHA256",
    "issued_at": "LITE_ISSUED_AT",
    "expires_at": "LITE_EXPIRES_AT",
    "run_id": "LITE_RUN_ID",
    "run_attempt": "LITE_RUN_ATTEMPT",
    "repository": "GITHUB_REPOSITORY",
}


def _read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    pathlib.Path(path).write_text(text, encoding="utf-8")
    return path


def _rule_input(role: str) -> dict:
    """Load the resolved rule input for C14. A missing one is a wiring error, not data.

    The workflow resolves it in its own step and publishes the path as ``LITE_RULE_INPUT``.
    If that is absent the round cannot be built honestly, so this stops rather than
    inventing an empty rule set - and it stops here, before any AI call.
    """
    if role != "c14":
        return {}
    path = os.environ.get("LITE_RULE_INPUT")
    if not path:
        raise SystemExit("spec: LITE_RULE_INPUT is required for c14 (and is not a dispatch input)")
    try:
        return _read(path)
    except (OSError, ValueError) as error:
        raise SystemExit(f"spec: cannot read LITE_RULE_INPUT {path}: {type(error).__name__}")


def _env_spec(role: str) -> dict:
    missing = [name for name, var in ENV_KEYS.items() if var != "GITHUB_REPOSITORY" and not os.environ.get(var)]
    if missing:
        raise SystemExit(f"missing dispatch env: {sorted(missing)}")
    return {
        "role": role,
        "cell_id": "C14" if role == "c14" else "C13",
        "candidate_sha": os.environ["LITE_CANDIDATE_SHA"],
        "application_tree": os.environ["LITE_APPLICATION_TREE"],
        "cell_pair": os.environ["LITE_CELL_PAIR"],
        "issue_number": int(os.environ["LITE_ISSUE_NUMBER"]) if os.environ.get("LITE_ISSUE_NUMBER") else None,
        "request_id": os.environ["LITE_REQUEST_ID"],
        "c14_task_id": os.environ["LITE_C14_TASK_ID"],
        "c13_task_id": os.environ["LITE_C13_TASK_ID"],
        "ledger_round_id": os.environ["LITE_LEDGER_ROUND_ID"],
        "nonce": os.environ["LITE_NONCE"],
        "workflow_identity": os.environ["LITE_WORKFLOW_IDENTITY"],
        "workflow_sha": os.environ["LITE_WORKFLOW_SHA"],
        "scope_sha256": os.environ["LITE_SCOPE_SHA256"],
        "issued_at": os.environ["LITE_ISSUED_AT"],
        "expires_at": os.environ["LITE_EXPIRES_AT"],
        "run_id": int(os.environ["LITE_RUN_ID"]),
        "run_attempt": int(os.environ["LITE_RUN_ATTEMPT"]),
        "repository": os.environ.get("GITHUB_REPOSITORY") or "yuguangzhi3836-glitch/GO",
        # Optional, and deliberately not part of the "missing dispatch env" check:
        # an empty value must fall back to the default, not fail the step. A push
        # triggered run has no inputs at all, which is exactly how this was found.
        "principal_id": os.environ.get("LITE_PRINCIPAL_ID") or "github-actions",
        "ai_model": os.environ.get("LITE_AI_MODEL") or lite_ai_reviewer.DEFAULT_MODEL,
        # Optional machine-test facts. Without a separate frozen inventory the
        # manifest itself is the inventory, which keeps the two digests linked.
        "test_inventory_sha256": os.environ.get("LITE_TEST_INVENTORY_SHA256", ""),
        "runner": os.environ.get("LITE_RUNNER", "ubuntu-24.04"),
        "runner_os": os.environ.get("LITE_RUNNER_OS", "Linux"),
        "postgres_version": os.environ.get("LITE_POSTGRES_VERSION", "18.4"),
        "docker_used": os.environ.get("LITE_DOCKER_USED", "true").lower() == "true",
        # The authoritatively declared rule sources, already resolved read-only from the
        # default branch's own commit by the ``rule-input`` step. Derived once here and
        # consumed by both the prompt facts and the sealed record, so the two cannot
        # disagree (CCV1-145B D-3, kept under the new field names).
        "rule_input": _rule_input(role),
        # Supplied by the scheduler adapter once it is wired; until then the
        # independence check is honest about not knowing the implementation run.
        "implementation_execution_id": os.environ.get("LITE_IMPLEMENTATION_EXECUTION_ID", "unknown-implementation-execution"),
    }


def _read_frozen_scope(path) -> dict:
    """Load the frozen scope this round bound, and refuse anything that is not that scope.

    The scope file is the ONE derivation of the change surface. Both facts builders read it
    from here, so the reviewer and the sealed record cannot describe different candidates -
    which is exactly what happened when `changed_paths` was filled from the spec instead:
    the spec has no such key, the reviewer was handed an empty change surface, and the
    record still sealed clean (CCV1-147B).
    """
    try:
        document = _read(path)
    except (OSError, ValueError) as error:
        raise SystemExit(f"spec: cannot read the frozen scope {path}: {type(error).__name__}")
    if not isinstance(document, dict) or not isinstance(document.get("scope"), dict):
        raise SystemExit(f"spec: {path} is not a scope record (no 'scope' object)")
    if document.get("scope_sha256") != lite_canonical.digest(document["scope"]):
        raise SystemExit(f"spec: {path} does not match its own scope digest")
    return document


def _read_candidate_diff(path) -> str:
    """The frozen candidate's complete pull-request diff; empty is a hard stop.

    An empty diff is not "a small change" - it is the reviewer being asked to review
    nothing, which is how a wrong input used to become a clean NOT_APPLICABLE.
    """
    try:
        raw = pathlib.Path(path).read_bytes()
    except OSError as error:
        raise SystemExit(f"spec: cannot read the candidate diff {path}: {type(error).__name__}")
    if not raw.strip():
        raise SystemExit(f"spec: the candidate diff {path} is empty (there is nothing to review)")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SystemExit(f"spec: the candidate diff {path} is not utf-8 text: {error.reason}")


def _junit_counts(path) -> dict:
    """The counts a quality reviewer can act on, read from the run's own junit XML."""
    import xml.etree.ElementTree as element_tree

    try:
        root = element_tree.parse(str(path)).getroot()
    except (OSError, element_tree.ParseError) as error:
        raise SystemExit(f"spec: cannot read the machine junit {path}: {type(error).__name__}")
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        raise SystemExit(f"spec: the machine junit {path} carries no testsuite element")
    counts = {}
    for name in ("tests", "failures", "errors", "skipped"):
        values = [suite.get(name) for suite in suites]
        present = [int(value) for value in values if value is not None and str(value).strip().isdigit()]
        counts[name] = sum(present) if present else None
    return counts


def _machine_evidence(manifest_path, junit_path) -> dict:
    """What the machine job actually produced, structured, for the quality reviewer.

    Read from the run's own manifest and junit, and copied verbatim rather than overwritten
    with anything from the dispatch: if the manifest ever names another candidate, that has
    to be visible in the facts instead of being silently replaced by the frozen one. No
    second evidence schema is invented here - these are the fields the manifest already has.
    """
    if not manifest_path:
        raise SystemExit("spec: c13 requires --machine-manifest (the machine evidence is an input)")
    if not junit_path:
        raise SystemExit("spec: c13 requires --junit (the machine evidence is an input)")
    try:
        manifest = _read(manifest_path)
    except (OSError, ValueError) as error:
        raise SystemExit(f"spec: cannot read the machine manifest {manifest_path}: {type(error).__name__}")
    if not isinstance(manifest, dict):
        raise SystemExit(f"spec: the machine manifest {manifest_path} is not an object")
    return {
        "inventory": manifest.get("inventory"),
        "candidate_sha": manifest.get("candidate_sha"),
        "application_tree": manifest.get("application_tree"),
        "docker_used": manifest.get("docker_used"),
        "postgres_version": manifest.get("postgres_version"),
        "database_observation": manifest.get("database_observation"),
        "database_sha256": manifest.get("database_sha256"),
        "evidence_parts": manifest.get("evidence_parts"),
        "part_sha256": manifest.get("part_sha256"),
        "junit": _junit_counts(junit_path),
        "junit_sha256": manifest.get("junit_sha256"),
        "stdout_sha256": manifest.get("stdout_sha256"),
    }


def _read_review_brief(path) -> dict:
    """The delivery brief declared by the candidate's own pull request.

    This is ``REVIEW_BRIEF_V1``: the associated pull request's declared delivery brief. It
    gives the reviewer task context, but it is **not** an immutable source of the original
    production task - a pull request body can be edited after it was opened, and this record
    only binds the brief the reviewer saw in this round. See ``lite_review_brief`` for the
    full statement of what it is and what it is not.

    Without a brief the reviewer knows what changed but not what was asked for, so it can only
    grade against its own idea of best practice - which is how an acceptable candidate is sent
    back for findings the declared brief never mentioned. A brief that could not be resolved is
    a hard stop, decided here before any AI call, and it is never replaced by a guessed pull
    request, a branch name or a default.
    """
    try:
        document = _read(path)
    except (OSError, ValueError) as error:
        raise SystemExit(f"spec: cannot read the review brief {path}: {type(error).__name__}")
    if not isinstance(document, dict) or document.get("schema_version") != lite_review_brief.SCHEMA_VERSION:
        raise SystemExit(f"spec: {path} is not a review brief record")
    if document.get("status") != "OK" or not isinstance(document.get("pull_request"), dict):
        raise SystemExit(
            "spec: there is no review brief for this candidate "
            f"({document.get('status')}: {document.get('reason')} - {document.get('detail')}); "
            "a review with no task to grade cannot be assembled")
    brief = document["pull_request"]
    if set(brief) != set(lite_review_brief.BRIEF_FIELDS) | {"matched_by"}:
        raise SystemExit(f"spec: {path} carries an unexpected review brief shape")
    return brief


def _assert_facts_carry_the_frozen_content(facts: dict, scope: dict) -> None:
    """The reviewer may not be told about a different change surface than the round froze.

    A post-condition, checked on the facts that are about to be written: it is satisfied by
    construction today, and its job is to stop the next edit that decides to derive the list
    again instead of reading the frozen one.
    """
    if list(facts.get("changed_paths") or []) != list(scope.get("changed_paths") or []):
        raise SystemExit("spec: the facts change surface is not the frozen scope's change surface")


def _facts(role: str, spec: dict, *, task_id: str, scope: dict, candidate_diff: str,
           review_brief: dict, machine_manifest=None, junit=None) -> dict:
    facts = {
        "repository": spec["repository"],
        "candidate_sha": spec["candidate_sha"],
        "application_tree": spec["application_tree"],
        "cell_id": spec["cell_id"],
        "task_id": task_id,
        "issue_number": spec["issue_number"],
        "ledger_reference": {
            "round_id": spec["ledger_round_id"],
            "cell_id": spec["cell_id"],
            "task_id": task_id,
        },
        # Read straight out of the scope this round froze: one derivation, and the reviewer is
        # its consumer. These two keys used to be filled from `spec`, which has no
        # `changed_paths` key at all - so the reviewer was handed an EMPTY change surface while
        # the frozen scope held eight paths, and it faithfully answered NOT_APPLICABLE for "no
        # changed paths". Every digest recomputed, so nothing failed (CCV1-147B).
        "changed_paths": list(scope["changed_paths"]),
        # And not only the names: the actual content this candidate brings in. These are git's
        # own bytes (the candidate's complete pull-request diff) - there is no diff authority, no
        # signature and no second registry behind them.
        "candidate_diff": candidate_diff,
        # And, from here on, WHICH TASK this is: the candidate's own pull request, frozen as
        # GitHub's raw facts. Both cells receive it, so both grade the same paper. It is a
        # plain facts key and nothing more - the existing facts digest binds it, so it needs
        # no signature, no second registry and no authority of its own.
        "review_brief": dict(review_brief),
    }
    if role == "c14":
        rule_input = spec["rule_input"]
        facts["rule_review_scope_sha256"] = spec["scope_sha256"]
        # Straight from the spec - the same derivation the sealed record projects from. The
        # rule TEXT travels inside the facts, which is enough to reach the reviewer: the
        # existing prompt builder serialises the whole facts object, so neither the reviewer
        # nor the prompt template needs to know that rule sources exist.
        facts["rule_sources"] = [
            {
                "repository_path": source["repository_path"],
                "git_blob_sha": source["git_blob_sha"],
                "sha256": source["sha256"],
                "rule_text": source["rule_text"],
            }
            for source in rule_input.get("sources", [])
        ]
        facts["rule_input_sha256"] = rule_input["rule_input_sha256"]
        facts["authority_commit"] = rule_input.get("authority_commit")
    else:
        facts["quality_test_scope_sha256"] = spec["scope_sha256"]
        facts["acceptance_criteria"] = list(scope.get("acceptance_criteria") or [])
        facts["machine_evidence"] = _machine_evidence(machine_manifest, junit)
    return facts


def _task_id(role: str, spec: dict) -> str:
    return spec["c14_task_id"] if role == "c14" else spec["c13_task_id"]


def cmd_spec(args) -> int:
    spec = _env_spec(args.role)
    if args.role == "c13" and (not args.machine_manifest or not args.junit):
        raise SystemExit("spec: c13 requires --machine-manifest and --junit (machine evidence is an input)")
    if args.role != "c13" and (args.machine_manifest or args.junit):
        raise SystemExit("spec: --machine-manifest and --junit are c13 only")
    # The frozen scope, not a re-derivation of it: the digest has to be the one this round
    # bound, and it has to be non-empty. Either check failing means the reviewer would be
    # asked to review something other than what was frozen, so the round stops here - before
    # any AI call - rather than producing a clean verdict over the wrong input (CCV1-147B).
    scope_document = _read_frozen_scope(args.scope)
    if scope_document["scope_sha256"] != spec["scope_sha256"]:
        raise SystemExit(
            "spec: the supplied scope is not the one this round bound "
            f"({scope_document['scope_sha256']} != {spec['scope_sha256']})")
    scope = scope_document["scope"]
    if not scope.get("changed_paths"):
        raise SystemExit("spec: the frozen scope carries no changed paths (there is nothing to review)")
    candidate_diff = _read_candidate_diff(args.candidate_diff)
    # The paper both cells grade. It was resolved from this same frozen candidate SHA by the
    # ``review-brief`` step, and it is re-checked against the candidate here rather than taken
    # on trust: a brief belonging to some other candidate would grade the wrong task.
    review_brief = _read_review_brief(args.review_brief)
    if spec["candidate_sha"] not in (review_brief["head_sha"], review_brief["merge_commit_sha"]):
        raise SystemExit("spec: the review brief does not belong to the frozen candidate")
    facts = _facts(args.role, spec, task_id=_task_id(args.role, spec), scope=scope,
                   candidate_diff=candidate_diff, review_brief=review_brief,
                   machine_manifest=args.machine_manifest,
                   junit=args.junit)
    _assert_facts_carry_the_frozen_content(facts, scope)
    prompt = lite_ai_reviewer.build_prompt(args.role, facts)
    contract = lite_candidate.build(
        repository=spec["repository"],
        candidate_commit_sha=spec["candidate_sha"],
        application_tree=spec["application_tree"],
        cell_id=spec["cell_id"],
        task_id=_task_id(args.role, spec),
        request_id=spec["request_id"],
        nonce=spec["nonce"],
        issued_at=spec["issued_at"],
        expires_at=spec["expires_at"],
        workflow_identity=spec["workflow_identity"],
        workflow_sha=spec["workflow_sha"],
        review_scope_sha256=spec["scope_sha256"],
        prompt_sha256=lite_canonical.digest_bytes(prompt.encode("utf-8")),
        issue_number=spec["issue_number"],
        ledger_reference={"round_id": spec["ledger_round_id"], "cell_id": spec["cell_id"], "task_id": _task_id(args.role, spec)},
    )
    _write(args.spec, spec)
    _write(args.facts, facts)
    _write(args.contract, contract)
    print(json.dumps({"spec": args.spec, "facts": args.facts, "contract": args.contract, "cell_id": spec["cell_id"]}))
    return 0


def cmd_review(args) -> int:
    spec = _read(args.spec)
    facts = _read(args.facts)
    role = spec["role"]
    if role == "c14" and spec.get("rule_input", {}).get("status") != "OK":
        # Fail-closed, and settled without touching the network: this round has no
        # authoritative rule source, so there is nothing to review against. Recording a
        # BLOCKED here - instead of calling the model and hoping - is what stops
        # "we have no rules to judge you by" from becoming a clean verdict.
        outcome = lite_rule_input.blocked_review_outcome(role, facts, spec["rule_input"])
        _write(args.out, outcome)
        print(json.dumps({"verdict": outcome["verdict"],
                          "decision_origin": outcome["decision_origin"],
                          "reason": spec["rule_input"].get("reason")}))
        # Deliberately 0: the round continues so the seal can publish the refusal. A
        # crashed step would leave no record of what was wrong (CCV1-145B D-4).
        return 0
    try:
        outcome = lite_ai_reviewer.run(
            role,
            facts,
            model=spec.get("ai_model", lite_ai_reviewer.DEFAULT_MODEL),
            api_key=os.environ.get("OPENAI_API_KEY"),
            stub=args.stub,
            checkpoint=lambda partial: _write_review_checkpoint(args.out, partial),
        )
    except lite_ai_reviewer.ReviewUnavailable as error:
        outcome = lite_ai_reviewer.failure_outcome(role, facts, error)
        _write(args.out, outcome)
        print(json.dumps({"verdict": outcome["verdict"], "failure_class": outcome["failure_class"]}))
        # A provider/quota failure is BLOCKED, not a crash and not a FAIL.
        return 0 if args.allow_blocked else 1
    _write(args.out, outcome)
    print(json.dumps({"verdict": outcome["verdict"], "ai_provider": outcome["ai_provider"]}))
    return 0


def _write_review_checkpoint(path, partial):
    """An interrupted batch run leaves a complete BLOCKED record, never a PASS."""
    temporary = str(path) + ".checkpoint"
    _write(temporary, partial)
    pathlib.Path(temporary).replace(path)


def _machine_job(spec: dict, artifacts: dict) -> dict:
    return {
        "runner": spec.get("runner", "ubuntu-24.04"),
        "runner_os": spec.get("runner_os", "Linux"),
        "postgres_version": spec.get("postgres_version", "18.4"),
        "docker_used": bool(spec.get("docker_used", True)),
        "test_inventory_sha256": spec.get("test_inventory_sha256") or lite_canonical.digest_bytes(artifacts["manifest"]),
        "junit_sha256": lite_canonical.digest_bytes(artifacts["junit"]),
        "stdout_sha256": lite_canonical.digest_bytes(artifacts["stdout"]),
        "manifest_sha256": lite_canonical.digest_bytes(artifacts["manifest"]),
    }


def cmd_seal(args) -> int:
    spec = _read(args.spec)
    contract = _read(args.contract)
    outcome = _read(args.outcome)
    role = spec["role"]
    facts_path = getattr(args, "facts", None)
    if role == "c13" and outcome.get("opinion") is None:
        # Legacy C13 bundles require an execution ID. Preserve raw BLOCKED
        # evidence instead of manufacturing blocked-<run> as a provider identity.
        raise lite_errors.Reject("c13_no_provider_opinion_raw_only")
    if outcome.get("review_mode") == "partitioned-v1" and outcome.get("opinion") is not None and not facts_path:
        raise lite_errors.Reject("partitioned_seal_requires_original_facts")
    try:
        lite_ai_reviewer.validate_outcome(outcome, facts=_read(facts_path) if facts_path else None)
    except (lite_ai_reviewer.ReviewUnavailable, KeyError, TypeError, ValueError) as error:
        raise lite_errors.Reject("outcome_verification_failed", str(error)) from error
    if outcome["role"] != role or outcome["prompt_sha256"] != contract["prompt_sha256"]:
        raise lite_errors.Reject("outcome_contract_binding_mismatch")
    if outcome.get("opinion") and outcome["opinion"]["candidate_sha"] != contract["candidate_commit_sha"]:
        raise lite_errors.Reject("outcome_candidate_mismatch")
    # Workflows publish the complete outcome envelope as *_opinion.json. Bind
    # those exact bytes, including all batch responses, not only its inner opinion.
    opinion_artifact_sha = lite_canonical.digest_bytes(pathlib.Path(args.outcome).read_bytes())
    import re
    for label, pattern in FORBIDDEN_SECRET_PATTERNS:
        if re.search(pattern, pathlib.Path(args.outcome).read_bytes()):
            raise lite_errors.Reject("opinion_artifact_secret_shape", label)
    cell_id = spec["cell_id"]
    fields = {
        "schema_version": lite_bundle.SCHEMA_VERSION_C14 if role == "c14" else lite_bundle.SCHEMA_VERSION_C13,
        "cell_id": cell_id,
        "task_id": contract["task_id"],
        "issue_number": contract["issue_number"],
        "ledger_reference": contract["ledger_reference"],
        "candidate_sha": contract["candidate_commit_sha"],
        "application_tree": contract["application_tree"],
        "nonce": contract["nonce"],
        "github_run_id": spec["run_id"],
        "github_run_attempt": spec["run_attempt"],
        "workflow_ref": f"{spec['repository']}/{spec['workflow_sha']}",
        "workflow_sha": spec["workflow_sha"],
        "ai_provider": outcome["ai_provider"],
        "ai_model": outcome["ai_model"] or "unavailable",
        "ai_execution_id": outcome["ai_execution_id"] or f"blocked-{spec['run_id']}-{spec['run_attempt']}",
        "principal_id": spec["principal_id"],
        "review_execution_id": outcome["ai_execution_id"] or f"blocked-{spec['run_id']}-{spec['run_attempt']}",
        "prompt_sha256": outcome["prompt_sha256"],
        "input_sha256": outcome["input_sha256"],
        "opinion_sha256": opinion_artifact_sha,
        "verdict": outcome["verdict"],
        "failure_class": outcome["failure_class"],
        "issued_at": spec["issued_at"],
        "authorizes_any_action": False,
    }
    if role == "c14":
        opinion = outcome.get("opinion") or {}
        rule_input = spec["rule_input"]
        origin = outcome.get("decision_origin")
        if origin not in lite_errors.DECISION_ORIGINS:
            # An outcome that does not say where it came from cannot be sealed as if it
            # did: that is how a backend refusal would end up looking like an AI verdict.
            raise lite_errors.Reject("c14_outcome_decision_origin_missing", str(origin))
        fields.update({
            "rule_review_scope_sha256": contract["review_scope_sha256"],
            # The rule sources this review was actually run against, plus the digest over
            # exactly those bytes. Both are projected from the same resolved rule input the
            # prompt facts were built from, so the record cannot declare a different rule set
            # than the reviewer saw (CCV1-145B D-3, kept under the new field names, and no
            # longer expressible as a list of names).
            "authority_commit": rule_input.get("authority_commit"),
            "rule_input_sha256": rule_input["rule_input_sha256"],
            "rule_sources": [lite_rule_input.identity(source) for source in rule_input.get("sources", [])],
            # Where the verdict came from. A precheck refusal must be readable as such, so
            # the AI identity fields are cleared rather than filled with something plausible:
            # there was no provider, no model and no execution (CCV1-145C).
            "decision_origin": origin,
            "ai_called": bool(outcome["ai_called"]),
            "ai_provider": outcome["ai_provider"],
            "ai_model": outcome["ai_model"],
            "ai_execution_id": outcome["ai_execution_id"],
            "review_execution_id": outcome["ai_execution_id"],
            "opinion_sha256": opinion_artifact_sha if outcome["opinion_sha256"] is not None else None,
            "not_applicable": (opinion or {}).get("not_applicable"),
            "findings": (opinion or {}).get("findings", []),
            "blocking_issues": list((opinion or {}).get("blocking_issues")
                                    or outcome.get("blocking_issues") or []),
            "remediation_status": (opinion or {}).get("remediation_status", "OPEN"),
        })
    else:
        artifacts = {
            "junit": pathlib.Path(args.junit).read_bytes(),
            "stdout": pathlib.Path(args.stdout).read_bytes(),
            "manifest": pathlib.Path(args.manifest).read_bytes(),
        }
        machine = _machine_job(spec, artifacts)
        prerequisite = _read(args.prereq)
        fields.update({
            "quality_test_scope_sha256": contract["review_scope_sha256"],
            "c14_prerequisite": {
                "c14_root": prerequisite[lite_bundle.C14_ROOT_FIELD],
                "c14_verdict": prerequisite["verdict"],
                "c14_candidate_sha": prerequisite["candidate_sha"],
                "c14_rule_scope_sha256": prerequisite["rule_review_scope_sha256"],
                "c14_remediation_closed": prerequisite["remediation_status"] in ("CLOSED", "NOT_REQUIRED"),
            },
            "machine_job": machine,
            "junit_sha256": machine["junit_sha256"],
            "stdout_sha256": machine["stdout_sha256"],
            "manifest_sha256": machine["manifest_sha256"],
            "quality_findings": (outcome.get("opinion") or {}).get("quality_findings", []),
            "remaining_risks": (outcome.get("opinion") or {}).get("remaining_risks", []),
        })
    lite_bundle.seal(fields)
    _write(args.out, fields)
    root_field = lite_bundle.C14_ROOT_FIELD if role == "c14" else lite_bundle.C13_ROOT_FIELD
    print(json.dumps({"bundle": args.out, root_field: fields[root_field], "verdict": fields["verdict"]}))
    return 0


def cmd_scope(args) -> int:
    """Freeze the review scope: the digest C13/C14 must both bind to.

    The two cells freeze different things, and C13's payload is deliberately untouched: it
    is already in production and its digest may not move (C13 is out of scope for this
    round). C14 binds the resolved rule input instead of a list of rule NAMES, so the
    frozen scope answers "which rule bytes" rather than "which names we declared".
    """
    changed = []
    if args.changed_paths:
        changed = sorted(line.strip() for line in pathlib.Path(args.changed_paths).read_text(encoding="utf-8").splitlines() if line.strip())
    inventory = sorted(line.strip() for line in pathlib.Path(args.inventory).read_text(encoding="utf-8").splitlines() if line.strip()) if args.inventory else []
    if args.role == "c14":
        # Rejected rather than ignored: silently dropping a rule set that used to matter is
        # exactly the failure this round removes.
        if args.rule or args.rule_version != "unversioned":
            raise SystemExit("scope: c14 takes no --rule/--rule-version; the rule set comes from the resolved rule input")
        rule_input = _read(args.rule_input) if args.rule_input else _rule_input("c14")
        payload = {
            "role": "c14",
            "authority_commit": rule_input.get("authority_commit"),
            "rule_input_sha256": rule_input["rule_input_sha256"],
            "rule_source_paths": sorted(source["repository_path"] for source in rule_input.get("sources", [])),
            "changed_paths": changed,
            "test_inventory": inventory,
            "acceptance_criteria": args.criterion or [],
        }
    else:
        rules = sorted(name for value in (args.rule or []) for name in value.split(",") if name.strip())
        payload = {
            "role": args.role,
            "rules": rules,
            "rule_version": args.rule_version,
            "changed_paths": changed,
            "test_inventory": inventory,
            "acceptance_criteria": args.criterion or [],
        }
    digest = lite_canonical.digest(payload)
    _write(args.out, {"scope": payload, "scope_sha256": digest})
    # Printed as JSON on stdout with exactly one 64-hex value in it: that is what the
    # workflow reads the digest from. scope.json carries the rule digest too, so grepping
    # the file itself would be ambiguous.
    print(json.dumps({"scope_sha256": digest, "changed_paths": len(changed),
                      "rule_input_sha256": payload.get("rule_input_sha256")}))
    return 0


def cmd_verify(args) -> int:
    spec = _read(args.spec)
    dispatch = {
        "candidate_sha": spec["candidate_sha"],
        "application_tree": spec["application_tree"],
        "cell_pair": spec["cell_pair"],
        "issue_number": spec["issue_number"],
        "request_id": spec["request_id"],
        "c14_task_id": spec["c14_task_id"],
        "c13_task_id": spec["c13_task_id"],
        "c14_ledger_reference": {"round_id": spec["ledger_round_id"], "cell_id": "C14", "task_id": spec["c14_task_id"]},
        "c13_ledger_reference": {"round_id": spec["ledger_round_id"], "cell_id": "C13", "task_id": spec["c13_task_id"]},
    }
    artifacts = {}
    for name, path in (("c14_opinion", args.c14_opinion), ("c13_opinion", args.c13_opinion),
                       ("junit", args.junit), ("stdout", args.stdout), ("manifest", args.manifest)):
        if path:
            artifacts[name] = pathlib.Path(path).read_bytes()
    decision = lite_chain.verify_round(
        c14_bundle=_read(args.c14_bundle),
        c13_bundle=_read(args.c13_bundle),
        c14_contract=_read(args.c14_contract),
        c13_contract=_read(args.c13_contract),
        dispatch=dispatch,
        implementation_execution_id=spec["implementation_execution_id"],
        artifacts=artifacts,
        now=None,
    )
    payload = decision.as_dict()
    _write(args.out, payload)
    print(json.dumps({"decision": payload["decision"], "reasons": decision.reasons, "eligibility": payload["eligibility"]}))
    if decision.ok or args.allow_incomplete:
        return 0
    return 1


def cmd_bind_ledger(args) -> int:
    spec = _read(args.spec)
    ledger = _read(args.ledger)
    c14_bundle = _read(args.c14_bundle)
    c13_bundle = _read(args.c13_bundle)
    evidence_root = pathlib.Path(args.evidence_root)
    c14_record = lite_execution_record.build(
        c14_bundle,
        artifact={"name": args.c14_artifact_name, "id": args.c14_artifact_id, "digest": args.c14_artifact_digest},
        evidence_path=args.c14_bundle,
    )
    c13_record = lite_execution_record.build(
        c13_bundle,
        artifact={"name": args.c13_artifact_name, "id": args.c13_artifact_id, "digest": args.c13_artifact_digest},
        evidence_path=args.c13_bundle,
    )
    machine_files = [pathlib.Path(p) for p in (args.junit, args.stdout, args.manifest)]
    bound = lite_ledger_binding.bind(
        ledger,
        evidence_root=evidence_root,
        candidate_sha=spec["candidate_sha"],
        c14_record=c14_record,
        c13_record=c13_record,
        c14_evidence=[(args.c14_bundle, pathlib.Path(args.c14_bundle).read_bytes())],
        c13_evidence=[(args.c13_bundle, pathlib.Path(args.c13_bundle).read_bytes())],
        machine_evidence=[(_relpath(p, evidence_root), p.read_bytes()) for p in machine_files],
        completed_at=args.completed_at,
        mark_tasks_done=not args.keep_assigned,
    )
    report = lite_ledger_binding.validate_with_repository_validator(bound, evidence_root)
    _write(args.out_bound, bound)
    _write(args.out_report, report)
    print(json.dumps({"ledger_gate": report["gate"], "errors": report["errors"]}))
    return 0 if report["gate"] == "PASS_SCOPED" else 1


def _relpath(path, root):
    try:
        return pathlib.Path(path).resolve().relative_to(pathlib.Path(root).resolve()).as_posix()
    except ValueError as error:
        raise lite_errors.Reject("evidence_outside_root", str(path)) from error


def _git_blob_sha(raw: bytes) -> str:
    """The SHA git itself would give these bytes (blob header, length, content)."""
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def cmd_workflow_identity(args) -> int:
    """Resolve the blob SHA of the workflow definition that is actually executing.

    CCV1-145B D-2: inferring the identity from the workspace points the record at whatever
    copy of the file happens to be checked out there, not at the definition GitHub
    registered for this run - and a later edit to the registered workflow then does not
    move the digest at all. The definition that ran lives at the ref this run used
    (``GITHUB_SHA``); since the backend is no longer pinned to a branch-local commit that
    ref is also the execution backend. It is read from the API here, and the bytes the API
    returns are re-hashed into git's own blob SHA before anything is reported, so the
    printed value is computed from the content rather than taken on the API's word.

    Fail-closed on purpose: an unbound workflow identity must stop the round rather than be
    silently recorded as some other commit's file. There is no fallback value.
    """
    import base64
    import urllib.error
    import urllib.parse
    import urllib.request

    repository = args.repository or os.environ.get("GITHUB_REPOSITORY") or ""
    if not repository:
        raise SystemExit("workflow-identity: no repository (set GITHUB_REPOSITORY or --repository)")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("workflow-identity: no token (set GH_TOKEN or GITHUB_TOKEN)")
    if not args.ref.strip():
        raise SystemExit("workflow-identity: --ref is required")

    quoted_path = "/".join(urllib.parse.quote(part) for part in args.path.split("/") if part)
    url = (f"https://api.github.com/repos/{repository}/contents/{quoted_path}"
           f"?ref={urllib.parse.quote(args.ref)}")
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "go-c13-c14-lite-workflow-identity",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SystemExit(f"workflow-identity: HTTP {error.code} for {args.path}@{args.ref}")
    except Exception as error:  # noqa: BLE001 - any transport failure is a hard stop
        raise SystemExit(f"workflow-identity: {type(error).__name__} for {args.path}@{args.ref}")

    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise SystemExit(f"workflow-identity: {args.path}@{args.ref} is not a base64 file object")
    content = payload.get("content")
    if not isinstance(content, str):
        raise SystemExit(f"workflow-identity: {args.path}@{args.ref} has no inline content")
    raw = base64.b64decode(content)
    recomputed = _git_blob_sha(raw)
    if payload.get("sha") != recomputed:
        raise SystemExit(
            "workflow-identity: the reported blob sha does not match the returned bytes "
            f"({payload.get('sha')} != {recomputed})")
    print(recomputed)
    return 0


RAW_EVIDENCE_SCHEMA_VERSION = "go.c13c14.lite.raw_review_evidence.v1"

#: Shapes that must never leave the runner.
#:
#: The recorded artefacts are produced by the backend from dispatch inputs and the reviewer's
#: opinion, and none of them has a credential field - so this is a backstop against a future
#: edit rather than a filter over live secrets. It is deliberately **shape-based**: the AI
#: credential is NOT passed to this step, so the guard cannot widen the secret's blast radius.
FORBIDDEN_SECRET_PATTERNS = (
    ("openai_key", rb"sk-[A-Za-z0-9_\-]{16,}"),
    ("private_key_block", rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("github_fine_grained_pat", rb"github_pat_[A-Za-z0-9_]{20,}"),
    ("github_token", rb"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    ("aws_access_key", rb"\bAKIA[0-9A-Z]{16}\b"),
    ("aliyun_access_key", rb"\bLTAI[A-Za-z0-9]{12,}\b"),
    ("bearer_header", rb"Bearer\s+[A-Za-z0-9._\-]{20,}"),
)


def cmd_raw_evidence(args) -> int:
    """Preserve the raw review record so a refused seal cannot destroy the only copy.

    CCV1-145B D-4: when the seal refuses, the reviewer's findings and summary - and with them
    the ability to say *why* the verdict was what it was - live only in the runner's temp
    directory and are discarded with the job. This gathers the non-secret review artefacts into
    one directory, proves no credential shape is among them, and writes a manifest with digests.

    It deliberately does not produce a sealed bundle: raw review evidence is not sealed
    evidence, and only the seal step may publish that. ``authorizes_any_action`` stays false.
    """
    import re

    stage = {
        "spec": args.spec,
        "facts": args.facts,
        "contract": args.contract,
        "outcome": args.outcome,
        "scope": args.scope,
        # The brief is staged for the same reason as everything else here: when a round is
        # refused, "what task was it being graded against" is part of why the refusal happened.
        "review_brief": args.review_brief,
        "seal_result": args.seal_result,
        "seal_stdout": args.seal_stdout,
        "seal_stderr": args.seal_stderr,
    }

    # Scan everything BEFORE writing anything. A partial directory would be worse than none:
    # it would look like a complete raw record while quietly missing the file that leaked.
    staged, missing, projections = [], [], []
    for name, source in sorted(stage.items()):
        if not source:
            continue
        path = pathlib.Path(source)
        if not path.is_file():
            missing.append(name)
            continue
        raw = path.read_bytes()
        suffix = path.suffix or ".txt"
        if name == "facts":
            raw, projection = _public_facts_projection(raw)
            if projection is not None:
                projections.append(projection)
                # Never label transformed bytes as the original frozen facts.
                name, suffix = "facts_redacted_projection", ".json"
        for label, pattern in FORBIDDEN_SECRET_PATTERNS:
            if re.search(pattern, raw):
                raise SystemExit(f"raw-evidence: refusing to publish {name}: matches {label}")
        staged.append((name, suffix, raw))

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    collected = []
    for name, suffix, raw in staged:
        (out / f"{name}{suffix}").write_bytes(raw)
        collected.append({"name": name, "file": f"{name}{suffix}",
                          "bytes": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest()})

    seal_status = None
    seal_result_file = out / f"seal_result{pathlib.Path(args.seal_result).suffix or '.txt'}" \
        if args.seal_result else None
    if seal_result_file and seal_result_file.is_file():
        seal_status = json.loads(seal_result_file.read_text("utf-8"))

    manifest = {
        "schema_version": RAW_EVIDENCE_SCHEMA_VERSION,
        "files": collected,
        "missing": missing,
        "redacted_projections": projections,
        "seal_status": seal_status,
        "sealed_bundle_published_by_this_step": False,
        "authorizes_any_action": False,
    }
    _write(out / "raw_evidence_manifest.json", manifest)
    print(json.dumps({"raw_evidence": str(out), "files": len(collected),
                      "missing": missing, "seal_status": seal_status}))
    return 0


def _public_facts_projection(raw):
    """Redact only bearer values in the diff for publication, never for review.

    Other secret shapes and every other facts field still fail the existing
    scan-before-write guard. The original facts file and all frozen digests are
    untouched. This projection is diagnostic, not a replacement seal input.
    """
    import re

    try:
        facts = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return raw, None  # Existing secret scan still applies.
    if not isinstance(facts, dict) or not isinstance(facts.get("candidate_diff"), str):
        return raw, None
    diff = facts["candidate_diff"]
    # Horizontal whitespace only: preserve every diff line and hunk boundary.
    pattern = re.compile(r"\bBearer[ \t]+[A-Za-z0-9._\-]{20,}")
    matches = list(pattern.finditer(diff))
    safe_diff = pattern.sub("Bearer [REDACTED]", diff)
    # Scan decoded text as well: JSON escaping must not hide a multiline secret.
    for label, forbidden in FORBIDDEN_SECRET_PATTERNS:
        if re.search(forbidden, safe_diff.encode("utf-8")):
            raise SystemExit(f"raw-evidence: refusing to publish facts: matches {label}")
    if not matches:
        return raw, None
    facts["candidate_diff"] = safe_diff
    projected = (json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    receipt = {
        "source": "facts",
        "field": "candidate_diff",
        "original_bytes_sha256": hashlib.sha256(raw).hexdigest(),
        "original_canonical_sha256": lite_canonical.digest(json.loads(raw)),
        "projection_bytes_sha256": hashlib.sha256(projected).hexdigest(),
        "redaction_count": len(matches),
        "redacted_line_numbers": [diff.count("\n", 0, match.start()) + 1 for match in matches],
        "original_available_in_artifact": False,
        "authorizes_any_action": False,
    }
    return projected, receipt


def cmd_review_brief(args) -> int:
    """Resolve the candidate's own pull request read-only, or record why we cannot.

    Always exits 0, like ``rule-input``: a refusal is a *recorded* BLOCKED, and the ``spec``
    step then refuses to build a round from it - so the reason survives instead of being lost
    in a crashed step. Settling it here also settles it before any AI call, which matters: a
    reviewer with no brief can only grade the candidate against its own idea of best practice.

    The association is GitHub's own commit -> pull requests answer, and it has to be unique.
    A title, a branch name, a recency order or "the first result" is never used to break a
    tie; an unresolvable or ambiguous lookup is a refusal, not a guess.
    """
    repository = args.repository or os.environ.get("GITHUB_REPOSITORY") or ""
    if not repository:
        raise SystemExit("review-brief: no repository (set GITHUB_REPOSITORY or --repository)")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("review-brief: no token (set GH_TOKEN or GITHUB_TOKEN)")
    list_pulls = lite_review_brief.github_pull_reader(repository, token)
    record = lite_review_brief.resolve(args.candidate_sha, list_pulls)
    _write(args.out, record)
    print(json.dumps({"review_brief_status": record["status"], "reason": record["reason"],
                      "matched_by": record["matched_by"],
                      "pull_request_number": (record["pull_request"] or {}).get("number")}))
    return 0


def cmd_rule_input(args) -> int:
    """Resolve the declared rule sources read-only, or record why we cannot.

    Always exits 0. A refusal is a *recorded* BLOCKED (``decision_origin =
    DETERMINISTIC_PRECHECK``) which the seal step publishes - not a crashed step. Failing
    the job here would produce a red run with no record of what was wrong, which is the
    mistake CCV1-145B D-4 already taught us not to repeat.
    """
    repository = args.repository or os.environ.get("GITHUB_REPOSITORY") or ""
    if not repository:
        raise SystemExit("rule-input: no repository (set GITHUB_REPOSITORY or --repository)")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("rule-input: no token (set GH_TOKEN or GITHUB_TOKEN)")
    changed = []
    if args.changed_paths:
        changed = [line.strip() for line in pathlib.Path(args.changed_paths).read_text(encoding="utf-8").splitlines() if line.strip()]
    resolve_commit, read_file = lite_rule_input.github_reader(repository, token)
    record = lite_rule_input.resolve(ref=args.ref, resolve_commit=resolve_commit,
                                     read_file=read_file, changed_paths=changed)
    _write(args.out, record)
    print(json.dumps({"rule_input_status": record["status"], "reason": record["reason"],
                      "authority_commit": record.get("authority_commit"),
                      "rule_input_sha256": record["rule_input_sha256"],
                      "sources": [source["repository_path"] for source in record["sources"]]}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    spec = sub.add_parser("spec")
    spec.add_argument("--role", required=True, choices=("c13", "c14"))
    spec.add_argument("--spec", required=True)
    spec.add_argument("--facts", required=True)
    spec.add_argument("--contract", required=True)
    # Required, not optional: without them the reviewer is handed an empty change surface and
    # an empty diff, which is exactly the defect this round removes (CCV1-147B). There is no
    # default to fall back to and no dispatch input was added for them - both are files the
    # run already produced.
    spec.add_argument("--scope", required=True,
                      help="the scope.json this round froze; the change surface is read from it")
    spec.add_argument("--candidate-diff", required=True,
                      help="the frozen candidate's complete pull-request diff")
    # Required for the same reason one level up: the diff is the answer, the brief is the
    # question. Without it a reviewer can only grade against its own idea of best practice.
    # It is the association's *declared* brief (REVIEW_BRIEF_V1), not an immutable original
    # task - see lite_review_brief for what that does and does not establish.
    spec.add_argument("--review-brief", required=True,
                      help="the review-brief record for this candidate (the PR-declared delivery brief being graded)")
    spec.add_argument("--machine-manifest", help="c13 only: the machine-test manifest.json")
    spec.add_argument("--junit", help="c13 only: the machine-test junit.xml")
    spec.set_defaults(func=cmd_spec)

    scope = sub.add_parser("scope")
    scope.add_argument("--role", required=True, choices=("c13", "c14"))
    scope.add_argument("--rule", action="append", help="repeatable; c13 only")
    scope.add_argument("--rule-version", default="unversioned", help="c13 only")
    scope.add_argument("--rule-input", help="c14 only: the resolved rule input from rule-input")
    scope.add_argument("--changed-paths", help="file with one repository path per line")
    scope.add_argument("--inventory", help="file with one test-inventory entry per line")
    scope.add_argument("--criterion", action="append", help="repeatable acceptance criterion")
    scope.add_argument("--out", required=True)
    scope.set_defaults(func=cmd_scope)

    review = sub.add_parser("review")
    review.add_argument("--spec", required=True)
    review.add_argument("--facts", required=True)
    review.add_argument("--out", required=True)
    review.add_argument("--stub", action="store_true")
    review.add_argument("--allow-blocked", action="store_true")
    review.set_defaults(func=cmd_review)

    seal = sub.add_parser("seal")
    seal.add_argument("--spec", required=True)
    seal.add_argument("--contract", required=True)
    seal.add_argument("--outcome", required=True)
    seal.add_argument("--facts", help="original frozen facts; required to seal a partitioned opinion")
    seal.add_argument("--out", required=True)
    seal.add_argument("--prereq")
    seal.add_argument("--junit")
    seal.add_argument("--stdout")
    seal.add_argument("--manifest")
    seal.set_defaults(func=cmd_seal)

    verify = sub.add_parser("verify")
    verify.add_argument("--spec", required=True)
    verify.add_argument("--c14-bundle", required=True)
    verify.add_argument("--c13-bundle", required=True)
    verify.add_argument("--c14-contract", required=True)
    verify.add_argument("--c13-contract", required=True)
    verify.add_argument("--c14-opinion")
    verify.add_argument("--c13-opinion")
    verify.add_argument("--junit")
    verify.add_argument("--stdout")
    verify.add_argument("--manifest")
    verify.add_argument("--out", required=True)
    verify.add_argument("--allow-incomplete", action="store_true",
                        help="write the decision and exit 0 even when it is not ACCEPT (the decision file still carries the truth)")
    verify.set_defaults(func=cmd_verify)

    brief = sub.add_parser("review-brief")
    brief.add_argument("--candidate-sha", required=True,
                       help="the frozen candidate commit SHA (its PR head or merge commit)")
    brief.add_argument("--out", required=True)
    brief.add_argument("--repository", help="defaults to GITHUB_REPOSITORY")
    brief.set_defaults(func=cmd_review_brief)

    rulein = sub.add_parser("rule-input")
    rulein.add_argument("--out", required=True)
    rulein.add_argument("--repository", help="defaults to GITHUB_REPOSITORY")
    rulein.add_argument("--ref", default=lite_rule_input.DEFAULT_AUTHORITY_REF,
                        help="the default branch; deliberately not a dispatch input")
    rulein.add_argument("--changed-paths", help="file with one repository path per line")
    rulein.set_defaults(func=cmd_rule_input)

    wfid = sub.add_parser("workflow-identity")
    wfid.add_argument("--path", required=True, help="repository-relative workflow path")
    wfid.add_argument("--ref", required=True, help="the ref this run used (GITHUB_SHA)")
    wfid.add_argument("--repository", help="defaults to GITHUB_REPOSITORY")
    wfid.set_defaults(func=cmd_workflow_identity)

    rawev = sub.add_parser("raw-evidence")
    rawev.add_argument("--out", required=True, help="directory to assemble the raw record in")
    rawev.add_argument("--spec")
    rawev.add_argument("--facts")
    rawev.add_argument("--contract")
    rawev.add_argument("--outcome")
    rawev.add_argument("--scope")
    rawev.add_argument("--review-brief")
    rawev.add_argument("--seal-result")
    rawev.add_argument("--seal-stdout")
    rawev.add_argument("--seal-stderr")
    rawev.set_defaults(func=cmd_raw_evidence)

    bind = sub.add_parser("bind-ledger")
    bind.add_argument("--spec", required=True)
    bind.add_argument("--ledger", required=True)
    bind.add_argument("--evidence-root", required=True)
    bind.add_argument("--c14-bundle", required=True)
    bind.add_argument("--c13-bundle", required=True)
    bind.add_argument("--junit", required=True)
    bind.add_argument("--stdout", required=True)
    bind.add_argument("--manifest", required=True)
    bind.add_argument("--completed-at", required=True)
    bind.add_argument("--c14-artifact-name", required=True)
    bind.add_argument("--c14-artifact-id", type=int, required=True)
    bind.add_argument("--c14-artifact-digest", required=True)
    bind.add_argument("--c13-artifact-name", required=True)
    bind.add_argument("--c13-artifact-id", type=int, required=True)
    bind.add_argument("--c13-artifact-digest", required=True)
    bind.add_argument("--out-bound", required=True)
    bind.add_argument("--out-report", required=True)
    bind.add_argument("--keep-assigned", action="store_true")
    bind.set_defaults(func=cmd_bind_ledger)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (lite_errors.Reject, lite_errors.Block) as error:
        print(json.dumps({"refused": error.reason, "detail": getattr(error, "detail", "")}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
