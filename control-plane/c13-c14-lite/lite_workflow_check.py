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
        if "diff-tree" in line and CHANGED_PATHS_REDIRECT in line:
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


def _candidate_checkout_can_see_its_parent(name: str, raw: str) -> bool:
    """Whether some candidate checkout fetches deep enough to hold the first parent.

    A first-parent diff cannot be computed without the parent. At ``fetch-depth: 1`` the
    shallow graft makes the boundary come out EMPTY **with exit code 0** (measured), which
    is the same silent degradation as the diff-tree bug - the empty-boundary gate is the
    backstop, this is the early warning.
    """
    document = _document_from(raw)
    if document is not None:
        for job in (document.get("jobs") or {}).values():
            for step in (job or {}).get("steps", []) or []:
                if "checkout" not in str(step.get("uses", "")):
                    continue
                with_block = step.get("with") or {}
                if str(with_block.get("path") or "") != "candidate":
                    continue
                try:
                    if int(str(with_block.get("fetch-depth", 1))) >= 2:
                        return True
                except (TypeError, ValueError):
                    continue
        return False
    return bool(re.search(r"fetch-depth:\s*([2-9]|\d{2,})\b", raw))


def check_changed_path_boundary(name: str, raw: str, failures: list) -> None:
    """The frozen changed-path boundary must be correct on a MERGE commit.

    ``git diff-tree <merge>`` prints nothing unless a parent is selected, so the plain form
    silently froze an EMPTY boundary and the rule review became a review of nothing
    (CCV1-145B D-1 - proved by recomputing the frozen scope digest). This runs the
    workflow's *own* command against a throwaway repository holding both an ordinary commit
    and a merge commit, and compares it with git's own first-parent diff.

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
    if not _candidate_checkout_can_see_its_parent(name, raw):
        failures.append(
            f"{name}: the candidate checkout must fetch its first parent (fetch-depth >= 2); "
            "at depth 1 the boundary is empty again, with exit code 0")

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
            resolved = [str(repo) if token is None else token for token in argv]

            def produced():
                completed = subprocess.run(resolved, capture_output=True, text=True)
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip())
                return sorted(set(line for line in completed.stdout.splitlines() if line))

            merge_seen = produced()
            _git(repo, "checkout", "-q", "HEAD^1")
            ordinary_seen = produced()
            ordinary_expected = sorted(
                set(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
                         "HEAD^1", "HEAD").split()))
    except Exception as error:  # noqa: BLE001 - a boundary check that cannot run is a failure
        failures.append(f"{name}: could not evaluate the changed-path command ({error})")
        return

    if not merge_seen:
        failures.append(
            f"{name}: the changed-path boundary is EMPTY for a merge commit "
            "(the candidate's change surface would be reviewed as 'nothing changed')")
    elif merge_seen != ["f_side.txt"]:
        failures.append(f"{name}: merge boundary is {merge_seen}, expected ['f_side.txt']")
    if ordinary_seen != ordinary_expected:
        failures.append(
            f"{name}: boundary for an ordinary commit is {ordinary_seen}, "
            f"expected {ordinary_expected}")


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
        check_env_export_is_not_same_step(name, document, failures)
        check_readback_declares_the_run_head(name, raw, failures)
        check_changed_path_boundary(name, raw, failures)
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
