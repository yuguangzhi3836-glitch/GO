"""Structural contract checks for the two Lite V2 workflows.

These are the checks that must hold even when the workflow cannot be dispatched
from this workstation: least privilege, credential separation between the C13
machine job and the C13 AI job, no deployment authority, and a dispatchable
identity. They run offline and are part of the normal test suite.

Uses PyYAML when it is importable; otherwise falls back to a deliberately
conservative text scan so the suite still runs in a bare environment.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

C14_WORKFLOW = "c14-rule-compliance.yml"
C13_WORKFLOW = "c13-quality-acceptance.yml"
POC_WORKFLOW = "c13-c14-lite-poc.yml"

#: The two production workflows: the cells' execution backends on the default branch.
#: Everything in this module is about these two. The POC probe is a throwaway
#: quota/readback check that only ever lived on a working branch, so it is checked when it
#: is present and its absence is not a failure - demanding a file the default branch does
#: not carry would fail on the very branch this checker is meant to protect.
PRODUCTION_WORKFLOWS = (C14_WORKFLOW, C13_WORKFLOW)

FORBIDDEN_PERMISSION_SUFFIXES = ("write", "admin")
FORBIDDEN_CREDENTIAL_HINTS = ("SSH", "DEPLOY", "PRODUCTION", "AWS_", "ALIYUN", "HK_", "CC_")

#: Where the frozen changed-path boundary is written. The whole D-1 defect is that this
#: file could be legitimately *empty* without anything noticing.
CHANGED_PATHS_REDIRECT = "changed_paths.txt"

#: The three rule-set names our own backend used to hard-code as the C14 default.
#: Assembled rather than written out, so this module does not itself contain the strings
#: it forbids - the same reason the test fixtures build their values from seeds.
INVENTED_RULE_NAMES = ("GO_" + "CONSTITUTION", "PERMISSION_" + "BOUNDARY", "AI_BEHAVIOUR_" + "RULES")

#: The artifact that keeps the raw review record, so a refused seal cannot destroy the only
#: copy of the reviewer's reasoning (CCV1-145B D-4). Only C14 needs it: C13's always-run
#: verify step already copies its opinion into the uploaded artefact directory.
C14_RAW_ARTIFACT = "c13c14-lite-c14-raw-${{ inputs.candidate_sha }}"

#: The frozen candidate's complete pull-request diff. The reviewer has to be given the CONTENT,
#: not just the names of the files that changed.
CANDIDATE_DIFF_REDIRECT = "candidate.diff"

#: The resolved review brief - the delivery brief declared by the candidate's own pull request
#: (``REVIEW_BRIEF_V1``; declared, not an immutable original task). Read-only, and matched
#: uniquely or refused: the reviewer needs the question as well as the answer, or it grades
#: the candidate against its own idea of best practice.
REVIEW_BRIEF_REDIRECT = "review_brief.json"

try:  # pragma: no cover - trivial import guard
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load(name: str) -> dict:
    path = WORKFLOW_DIR / name
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        return {"__raw__": text}
    return yaml.safe_load(text)


def raw_of(document: dict, name: str) -> str:
    if "__raw__" in document:
        return document["__raw__"]
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def check_permissions(name: str, document: dict, raw: str, failures: list) -> None:
    permissions = document.get("permissions")
    if permissions is None:
        if not re.search(r"^permissions:", raw, re.M):
            failures.append(f"{name}: no permissions block (must be explicit, least privilege)")
        return
    if not isinstance(permissions, dict):
        failures.append(f"{name}: permissions must be a mapping")
        return
    for scope, value in permissions.items():
        if str(value).endswith(FORBIDDEN_PERMISSION_SUFFIXES) or value == "write-all":
            failures.append(f"{name}: forbidden permission {scope}={value}")
    for scope in ("contents", "actions"):
        if permissions.get(scope) != "read":
            failures.append(f"{name}: {scope} must be exactly read")


def check_no_deployment_authority(name: str, raw: str, failures: list) -> None:
    for pattern in (r"\bgit\s+merge\b", r"\bgit\s+push\b", r"\bgh\s+pr\s+merge\b",
                    r"deployments:\s*write", r"issues:\s*write", r"pull-requests:\s*write",
                    r"authorizes_any_action\s*[:=]\s*true"):
        if re.search(pattern, raw):
            failures.append(f"{name}: forbidden pattern {pattern}")


def check_credential_boundary(name: str, document: dict, raw: str, failures: list) -> None:
    """The C13 machine job must not see the AI key; the AI job must not run Docker."""
    if name != C13_WORKFLOW:
        return
    if "OPENAI_API_KEY" not in raw:
        failures.append(f"{name}: the AI review job must consume the AI credential")
    if yaml is None:
        return
    jobs = document.get("jobs") or {}
    machine = jobs.get("c13-machine-test")
    ai_review = jobs.get("c13-ai-review")
    if not machine or not ai_review:
        failures.append(f"{name}: expected both c13-machine-test and c13-ai-review jobs")
        return
    machine_text = json.dumps(machine)
    ai_text = json.dumps(ai_review)
    if "OPENAI_API_KEY" in machine_text:
        failures.append(f"{name}: machine job must not receive OPENAI_API_KEY")
    if "docker run" in ai_text or "services" in (ai_review or {}):
        failures.append(f"{name}: AI review job must not run Docker")
    if "postgres" in ai_text.lower() and "postgres_version" not in ai_text:
        failures.append(f"{name}: AI review job must not touch PostgreSQL")
    for hint in FORBIDDEN_CREDENTIAL_HINTS:
        if hint in machine_text:
            failures.append(f"{name}: machine job references a privileged credential hint {hint}")
    if str(ai_review.get("permissions")) not in ("None", "{}"):
        failures.append(f"{name}: AI job must not add write permissions of its own")


def check_dispatch_surface(name: str, document: dict, failures: list) -> None:
    if "__raw__" in document:
        return
    triggers = document.get("on") or document.get(True) or {}
    if "workflow_dispatch" not in triggers:
        failures.append(f"{name}: must be dispatchable with workflow_dispatch")
        return
    inputs = (triggers.get("workflow_dispatch") or {}).get("inputs") or {}
    for required in ("candidate_sha", "application_tree", "issue_number", "request_id"):
        if name == POC_WORKFLOW:
            continue
        if required not in inputs:
            failures.append(f"{name}: missing dispatch input {required}")
    if len(inputs) > 10:
        failures.append(f"{name}: workflow_dispatch allows at most 10 inputs")


def check_rule_input_is_governance_data(name: str, document: dict, raw: str, failures: list) -> None:
    """The C14 rule set must be resolved governance data, never a name the dispatch supplies.

    Both failures this pins were real (CCV1-145C): a round could be reviewed against three
    rule-set names our own backend invented and record them as if they were rules, and the
    manifest those names should have pointed at did not exist anywhere in the repository.
    "Process" never becomes evidence, and a round with nothing to judge against must fail
    closed rather than be judged against a constant we made up.
    """
    if name != C14_WORKFLOW:
        return
    for invented in INVENTED_RULE_NAMES:
        if invented in raw:
            failures.append(f"{name}: the invented rule-set name {invented} still appears")
    if "lite_cli.py rule-input" not in raw:
        failures.append(f"{name}: must resolve its rule sources with 'lite_cli.py rule-input'")
    if 'echo "LITE_RULE_INPUT=' not in raw:
        failures.append(f"{name}: must export LITE_RULE_INPUT into $GITHUB_ENV for later steps")
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if "lite_cli.py rule-input" in line:
            block = "\n".join(lines[index:index + 7])
            if "--changed-paths" not in block:
                failures.append(f"{name}: the rule-input step must be given the frozen change surface")
            if "--ref " not in block:
                failures.append(f"{name}: the rule-input step must name the default branch explicitly")
            break
    if "--rule " in raw and "lite_cli.py scope" in raw:
        failures.append(f"{name}: scope must take --rule-input, never a list of rule names")
    if "__raw__" in document:
        return
    triggers = document.get("on") or document.get(True) or {}
    inputs = (triggers.get("workflow_dispatch") or {}).get("inputs") or {}
    for forbidden in ("applicable_rules", "rule_version"):
        if forbidden in inputs:
            failures.append(f"{name}: {forbidden} must not be a dispatch input; the rule set is governance data")


def check_machine_step_installs_candidate_dependencies(name: str, document: dict, raw: str, failures: list) -> None:
    """C13's machine job must install what the CANDIDATE declares, not a fixed list.

    The first real C13 could not collect its inventory at all (CCV1-147A, measured): the
    machine job installed pytest and nothing else, while the candidate's own
    ``application/pyproject.toml`` declares the dependencies its tests import - the inventory
    the first machine job actually collected imported ``cryptography``, and only that
    declaration provides it. Installing a package list written inside this workflow would be
    the same defect one level down, so the check asks for an
    install OF THE CANDIDATE'S PROJECT rather than for any particular package name - and it
    asks for it before pytest runs, because after is the same as never.
    """
    if name != C13_WORKFLOW:
        return

    run = None
    document_parsed = _document_from(raw)
    if document_parsed is not None:
        for job in (document_parsed.get("jobs") or {}).values():
            for step in (job or {}).get("steps", []) or []:
                text = step.get("run") or ""
                if isinstance(text, str) and "python -m pytest" in text:
                    run = text
                    break
            if run is not None:
                break
    if run is None:
        run = raw
    if "python -m pytest" not in run:
        failures.append(f"{name}: no machine-test command found")
        return

    # Comments are stripped first, and deliberately so: the step explains the very defect this
    # check exists for, and quoting `pip install "/srv/application[dev]"` in that explanation
    # made the guard pass on a file whose real install had been deleted - measured, by mutation,
    # the first time this guard was written.
    code = "\n".join(_code_lines(run))
    # ``&&`` chains and plain lines are both legitimate shapes for the container command.
    commands = [part.strip() for part in code.split("&&")] if "&&" in code else [
        line.strip() for line in code.splitlines()]
    install_at = [index for index, part in enumerate(commands)
                  if re.search(r"pip install", part)]
    candidate_at = [index for index, part in enumerate(commands)
                    if re.search(r"pip install[^\n]*application", part)]
    pytest_at = [index for index, part in enumerate(commands)
                 if "python -m pytest" in part]
    if not install_at:
        failures.append(f"{name}: the machine step installs nothing before pytest")
        return
    if not candidate_at:
        failures.append(
            f"{name}: the machine step must install the candidate's own declared dependencies "
            "(a pip install of the candidate's application/ project). Installing only pytest, "
            "or a package list written in this file, cannot satisfy the inventory")
        return
    if pytest_at and min(candidate_at) > min(pytest_at):
        failures.append(
            f"{name}: the candidate's dependencies are installed after pytest runs")


def check_spec_carries_the_frozen_review_content(name: str, raw: str, failures: list) -> None:
    """The reviewer must be handed the CONTENT the round froze, not only its names.

    CCV1-147B, the first real Review E2E: the frozen scope carried eight changed paths while the
    facts handed to the model carried an empty list and no diff at all, so the model faithfully
    answered NOT_APPLICABLE for "no changed paths" - and nothing failed, because every digest
    still recomputed. The backend now refuses that round before any AI call; this is the
    structural half, so an edit that drops the arguments or the diff generation is caught at
    review time instead of by an unexplained red run.

    Comments are stripped first: this step's own explanation quotes the flags and would
    otherwise satisfy the check on the file it is warning about.
    """
    if name not in PRODUCTION_WORKFLOWS:
        return
    code = "\n".join(_code_lines(raw))
    if not any("git" in line and " diff " in line
               and f'> "$RUNNER_TEMP/{CANDIDATE_DIFF_REDIRECT}"' in line
               for line in code.splitlines()):
        failures.append(
            f"{name}: must freeze the candidate's complete pull-request diff into "
            f"$RUNNER_TEMP/{CANDIDATE_DIFF_REDIRECT} (file names alone are not the content the "
            "reviewer has to judge)")
    if f'test -s "$RUNNER_TEMP/{CANDIDATE_DIFF_REDIRECT}"' not in code:
        failures.append(f"{name}: must refuse an empty candidate diff")
    document = _document_from(raw)
    if document is None:
        return
    spec_steps = [step for job in (document.get("jobs") or {}).values()
                  for step in ((job or {}).get("steps") or [])
                  if "lite_cli.py spec" in str(step.get("run") or "")]
    if not spec_steps:
        failures.append(f"{name}: no 'lite_cli.py spec' step found")
        return
    required = ["--scope", "--candidate-diff", "--review-brief"]
    if name == C13_WORKFLOW:
        required += ["--machine-manifest", "--junit"]
    for step in spec_steps:
        step_code = "\n".join(_code_lines(str(step.get("run") or "")))
        for flag in required:
            if flag not in step_code:
                failures.append(
                    f"{name}: the spec step must be given {flag}; the frozen scope, the candidate "
                    "diff, the review brief and the machine evidence are inputs to the review, "
                    "not defaults")


def check_review_brief_is_resolved_read_only(name: str, raw: str, failures: list) -> None:
    """Both cells must be given the TASK, resolved read-only from the candidate's own PR.

    The runtime already fails closed: a brief that cannot be resolved uniquely, or that is
    absent, stops the round in ``spec`` before any AI call. This is the structural half, so an
    edit that drops the step or the argument is caught when the workflow is reviewed instead of
    by an unexplained red run - the same reason the diff/frozen-content check exists.

    It deliberately does not require any particular matching *implementation* here: it requires
    that the resolver is the backend subcommand (so the matching rule stays in reviewable Python
    and stays deterministic), that it is given the frozen candidate SHA, and that it writes the
    file ``spec`` is later handed.

    Comments are stripped first: the step's own explanation quotes these flags.
    """
    if name not in PRODUCTION_WORKFLOWS:
        return
    code = "\n".join(_code_lines(raw))
    lines = code.splitlines()
    resolver = [index for index, line in enumerate(lines) if "lite_cli.py review-brief" in line]
    if not resolver:
        failures.append(
            f"{name}: must resolve the review brief with 'lite_cli.py review-brief'; the "
            "reviewer needs the task, not only the change surface")
        return
    for index in resolver:
        block = "\n".join(lines[index:index + 6])
        if "--candidate-sha" not in block:
            failures.append(f"{name}: the review-brief step must be given the frozen candidate SHA")
        if f'$RUNNER_TEMP/{REVIEW_BRIEF_REDIRECT}' not in block:
            failures.append(
                f"{name}: the review-brief step must write $RUNNER_TEMP/{REVIEW_BRIEF_REDIRECT} "
                "for the spec step to consume")


def check_artifact_discipline(name: str, raw: str, failures: list) -> None:
    if "upload-artifact@v4" not in raw:
        failures.append(f"{name}: must publish a sealed artifact")
    if "retention-days" not in raw:
        failures.append(f"{name}: artifacts must declare retention-days")


def check_env_export_is_not_same_step(name: str, document: dict, failures: list) -> None:
    """$GITHUB_ENV values only exist for LATER steps.

    A step that *produces* a value and then immediately calls a ``lite_cli.py``
    subcommand that consumes it is a bug that only shows up on a real runner (it
    was an actual remote failure). ``scope`` produces the digest and is therefore
    allowed in the same step; ``spec`` / ``seal`` / ``review`` / ``verify`` /
    ``bind-ledger`` consume it and may not be.
    """
    if "__raw__" in document:
        return
    producers = ("LITE_SCOPE_SHA256", "LITE_TEST_INVENTORY_SHA256")
    consumers = ("spec", "seal", "review", "verify", "bind-ledger")
    for job_name, job in (document.get("jobs") or {}).items():
        for step in (job or {}).get("steps", []) or []:
            run = step.get("run") or ""
            if not isinstance(run, str):
                continue
            produced = [key for key in producers if re.search(rf'echo "{key}=', run)]
            if not produced:
                continue
            for subcommand in consumers:
                if re.search(rf"lite_cli\.py\s+{re.escape(subcommand)}\b", run):
                    failures.append(
                        f"{name}: step '{step.get('name')}' in job '{job_name}' exports {produced} and calls "
                        f"'lite_cli.py {subcommand}' in the same step (the exported value would not be visible)"
                    )
                    break


def check_readback_declares_the_run_head(name: str, raw: str, failures: list) -> None:
    """A readback must say which commit the workflow ref was at.

    The run's ``head_sha`` is the workflow ref commit, not the reviewed candidate
    (the candidate is checked out into a subdirectory). Omitting the flag would
    silently assert the wrong commit — this was a real failure on the first run.
    """
    for line in raw.splitlines():
        if "lite_readback.py" in line and "--expected-head-sha" not in raw:
            failures.append(f"{name}: lite_readback.py must be called with --expected-head-sha")
            return


def _code_lines(raw: str):
    """YAML lines with comments removed.

    A guard must never fire on its own explanation: the fixed workflows *quote* the broken
    form in a comment so the next reader knows why it is written that way, and a naive
    text scan would treat that comment as the defect it warns about.
    """
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        yield line.split(" #", 1)[0]


def check_workflow_identity_source(name: str, raw: str, failures: list) -> None:
    """The recorded ``workflow_sha`` must identify the definition that actually executed.

    CCV1-145B D-2: inferring the identity from the workspace means the record points at
    whatever copy of the file happens to be checked out there - not at the definition GitHub
    registered for this run - and a later edit to the registered workflow then does not move
    the digest at all. The identity must be resolved from the ref the run used (``GITHUB_SHA``:
    the execution backend, which is also the run's own commit) and checked against the API's
    own bytes, and it must be fail-closed rather than falling back to something plausible.
    "Pinned backend" is history: the backend used to be checked out at a fixed commit that
    only lived on an unmerged branch. It is the run's own commit now.

    The POC_ONLY probe is exempt: it is a throwaway quota/readback check, not a production
    record, and it has no ledger-bound identity to bind.
    """
    if name == POC_WORKFLOW:
        return
    code = "\n".join(_code_lines(raw))
    if re.search(r"rev-parse\s+HEAD:\$?\{?LITE_WORKFLOW_IDENTITY", code):
        failures.append(
            f"{name}: resolves the workflow identity from the pinned backend checkout "
            "(git rev-parse HEAD:$LITE_WORKFLOW_IDENTITY) instead of the executed definition")
    if "lite_cli.py workflow-identity" not in code:
        failures.append(
            f"{name}: the workflow identity must be resolved by 'lite_cli.py workflow-identity'")
    if 'echo "LITE_WORKFLOW_SHA=' not in code:
        failures.append(f"{name}: LITE_WORKFLOW_SHA must be exported into $GITHUB_ENV")


def _changed_paths_command(raw: str):
    """The exact pipeline the workflow uses to freeze the changed-path boundary."""
    for line in _code_lines(raw):
        if "git -C candidate diff --name-only" in line and CHANGED_PATHS_REDIRECT in line:
            return line.strip()
    return None


def _git(repo: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo), *args],
                               capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _boundary_fixture(root: pathlib.Path) -> pathlib.Path:
    """A throwaway repository holding one ordinary commit and one merge commit."""
    repo = root / "repo"
    repo.mkdir()
    identity = ("-c", "user.email=fixture@example.invalid", "-c", "user.name=fixture")
    _git(repo, "init", "-q")
    # `symbolic-ref`, not `rev-parse --abbrev-ref HEAD`: a freshly initialised repository
    # has no commit yet, so HEAD does not resolve (and the default branch name is not
    # guaranteed to be `main`).
    base_branch = _git(repo, "symbolic-ref", "--short", "HEAD").strip()

    (repo / "f_base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, *identity, "commit", "-q", "-m", "base")

    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "f_side.txt").write_text("side\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, *identity, "commit", "-q", "-m", "side")

    _git(repo, "checkout", "-q", base_branch)
    (repo / "f_mainline.txt").write_text("mainline\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, *identity, "commit", "-q", "-m", "mainline")

    _git(repo, *identity, "merge", "-q", "--no-ff", "side", "-m", "merge side")
    return repo


def _document_from(raw: str):
    """Parse the workflow text the caller handed us.

    Deliberately NOT ``load(name)``: re-reading the file by name made a check un-testable - a
    synthetic fixture silently validated whatever was on disk instead of the text under test,
    which is exactly the kind of false pass this module exists to prevent. Returns ``None``
    when there is no parser or the text does not parse, so the caller falls back to a scan.
    """
    if yaml is None:
        return None
    try:
        document = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001 - unparseable text falls back to the text scan
        return None
    return document if isinstance(document, dict) else None


def _workflow_fetches_the_exact_pr_base(raw: str) -> bool:
    """Whether the workflow resolves and fetches the exact GitHub-reported PR base SHA."""
    code = "\n".join(_code_lines(raw))
    return all(fragment in code for fragment in (
        ".pull_request.base_sha",
        'fetch-depth: 0',
        'test "$(git -C candidate rev-parse "$BASE_SHA^{commit}")" = "$BASE_SHA"',
        'test "$(git -C candidate rev-parse --is-shallow-repository)" = false',
    ))


def check_changed_path_boundary(name: str, raw: str, failures: list) -> None:
    """The frozen boundary must cover the complete PR for a head or merge candidate.

    A candidate head can contain several commits. ``HEAD^1..HEAD`` silently reviews only the
    newest commit, so the workflow must diff the exact PR base frozen from GitHub against the
    candidate. This runs the workflow's own command against a repository holding both forms.

    The POC_ONLY probe is exempt: it freezes no changed-path boundary at all.
    """
    if name == POC_WORKFLOW:
        return
    command = _changed_paths_command(raw)
    if command is None:
        failures.append(f"{name}: no changed-path extraction command found")
        return
    if "|| true" in command:
        failures.append(f"{name}: the changed-path extraction swallows its own failure (|| true)")
    if f'test -s "$RUNNER_TEMP/{CHANGED_PATHS_REDIRECT}"' not in raw:
        failures.append(
            f"{name}: must refuse an empty changed-path boundary "
            f"(no 'test -s \"$RUNNER_TEMP/{CHANGED_PATHS_REDIRECT}\"')")
    if not _workflow_fetches_the_exact_pr_base(raw):
        failures.append(
            f"{name}: must resolve, fetch and verify the exact PR base SHA before diffing")

    pipeline = command.split(">", 1)[0].strip()
    head, _, tail = pipeline.partition("|")
    if tail.strip() != "sort -u":
        failures.append(
            f"{name}: unexpected post-processing of the changed-path list: {tail.strip()!r}")

    # Split on whitespace and swap the checkout target as its own argv element. Using
    # shlex here would eat the backslashes of a Windows fixture path.
    argv = head.split()
    for index, token in enumerate(argv):
        if token == "-C" and index + 1 < len(argv) and argv[index + 1] == "candidate":
            argv[index + 1] = None

    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _boundary_fixture(pathlib.Path(tmp))
            base_sha = _git(repo, "rev-parse", "HEAD^1").strip()
            resolved = []
            for token in argv:
                if token is None:
                    resolved.append(str(repo))
                elif "BASE_SHA" in token:
                    resolved.append(base_sha + ("...HEAD" if "...HEAD" in token else ""))
                else:
                    resolved.append(token.strip('"'))

            def produced():
                completed = subprocess.run(resolved, capture_output=True, text=True)
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip())
                return sorted(set(line for line in completed.stdout.splitlines() if line))

            merge_seen = produced()
            _git(repo, "checkout", "-q", "side")
            ordinary_seen = produced()
    except Exception as error:  # noqa: BLE001 - a boundary check that cannot run is a failure
        failures.append(f"{name}: could not evaluate the changed-path command ({error})")
        return

    if not merge_seen:
        failures.append(
            f"{name}: the changed-path boundary is EMPTY for a merge commit "
            "(the candidate's change surface would be reviewed as 'nothing changed')")
    elif merge_seen != ["f_side.txt"]:
        failures.append(f"{name}: merge boundary is {merge_seen}, expected ['f_side.txt']")
    if ordinary_seen != ["f_side.txt"]:
        failures.append(
            f"{name}: boundary for an ordinary commit is {ordinary_seen}, "
            "expected ['f_side.txt']")


def check_raw_evidence_survives_a_refused_seal(name: str, raw: str, failures: list) -> None:
    """A refused seal must not destroy the only copy of the reviewer's reasoning.

    CCV1-145B D-4: the seal can legitimately refuse (a model-authored `BLOCKED` used to be
    unsealable), and the review artefacts lived only in the runner's temp directory - so the run
    failed and the reason for the verdict was lost with it. The workflow must publish the raw
    review record **unconditionally**, while still publishing the **sealed** bundle only when a
    seal actually succeeded: raw review evidence is not sealed evidence.

    Only the C14 workflow needs this. C13's always-run "verify" step already copies its opinion
    into the uploaded artefact directory before the seal can refuse, so it does not share the
    defect - and this guard deliberately does not invent a requirement for it.
    """
    if name != C14_WORKFLOW:
        return
    document = _document_from(raw)
    if document is None:
        # No parser, or the text does not parse: fall back to the two load-bearing facts.
        if "lite_cli.py raw-evidence" not in raw:
            failures.append(f"{name}: must assemble the raw review record (lite_cli.py raw-evidence)")
        if f"name: {C14_RAW_ARTIFACT}" not in raw:
            failures.append(f"{name}: must publish the raw review record as its own artifact")
        return

    raw_steps, raw_uploads, sealed_uploads = [], [], []
    # The sealed bundle is the artifact whose name carries the cell and the candidate and no
    # other role suffix. Matching on a prefix instead would also catch the -raw- and -readback-
    # artifacts, both of which are *supposed* to be published unconditionally.
    sealed_name = "c13c14-lite-c14-${{ inputs.candidate_sha }}"
    for job in (document.get("jobs") or {}).values():
        for step in (job or {}).get("steps", []) or []:
            run = step.get("run") or ""
            if isinstance(run, str) and "lite_cli.py raw-evidence" in run:
                raw_steps.append((step, run))
            if "upload-artifact" in str(step.get("uses", "")):
                artifact = str((step.get("with") or {}).get("name") or "").strip()
                if "-raw-" in artifact:
                    raw_uploads.append((step.get("if"), artifact))
                elif artifact == sealed_name:
                    sealed_uploads.append((step.get("if"), artifact))

    if not raw_steps:
        failures.append(f"{name}: must assemble the raw review record (lite_cli.py raw-evidence)")
    for step, run in raw_steps:
        if str(step.get("if")) != "always()":
            failures.append(f"{name}: the raw-evidence step must run under 'if: always()'")
        for required in ("--outcome", "--contract", "--seal-result"):
            if required not in run:
                failures.append(f"{name}: the raw-evidence step must carry {required}")

    if not raw_uploads:
        failures.append(f"{name}: must publish the raw review record as its own artifact")
    for condition, _ in raw_uploads:
        if str(condition) != "always()":
            failures.append(f"{name}: the raw review artifact must be uploaded under 'if: always()'")

    if not sealed_uploads:
        failures.append(f"{name}: the sealed bundle artifact is missing")
    for condition, _ in sealed_uploads:
        if str(condition) == "always()":
            failures.append(
                f"{name}: the SEALED bundle artifact must not be published unconditionally - "
                "raw review evidence is not sealed evidence")


def workflow_names() -> list:
    """The workflows this checker runs over: the two production ones, plus POC if present."""
    names = list(PRODUCTION_WORKFLOWS)
    if (WORKFLOW_DIR / POC_WORKFLOW).is_file():
        names.append(POC_WORKFLOW)
    return names


def run() -> dict:
    failures = []
    checked = []
    for name in workflow_names():
        if not (WORKFLOW_DIR / name).is_file():
            failures.append(f"{name}: missing")
            continue
        checked.append(name)
        document = load(name)
        raw = raw_of(document, name)
        check_permissions(name, document, raw, failures)
        check_no_deployment_authority(name, raw, failures)
        check_credential_boundary(name, document, raw, failures)
        check_dispatch_surface(name, document, failures)
        check_artifact_discipline(name, raw, failures)
        check_spec_carries_the_frozen_review_content(name, raw, failures)
        check_review_brief_is_resolved_read_only(name, raw, failures)
        check_env_export_is_not_same_step(name, document, failures)
        check_readback_declares_the_run_head(name, raw, failures)
        check_changed_path_boundary(name, raw, failures)
        check_machine_step_installs_candidate_dependencies(name, document, raw, failures)
        check_workflow_identity_source(name, raw, failures)
        check_raw_evidence_survives_a_refused_seal(name, raw, failures)
        check_rule_input_is_governance_data(name, document, raw, failures)
    return {
        "gate": "PASS" if not failures else "FAIL",
        "yaml_parser": "PyYAML" if yaml is not None else "text-scan-fallback",
        "checked": checked,
        "failures": failures,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    report = run()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
