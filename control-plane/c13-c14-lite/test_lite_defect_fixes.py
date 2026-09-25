"""Regression guards for the three defects the first real production C14 dispatch exposed.

Each test is written to be **RED against the code as it stood when the defects were found**
and GREEN after the fix:

    D-1  the frozen changed-path boundary was EMPTY for a merge commit, so the rule review
         became a review of nothing
    D-2  the recorded ``workflow_sha`` identified the pinned backend checkout's copy of the
         workflow file, not the definition that actually executed
    D-3  the sealed record declared a *smaller* rule set than the one the prompt was built
         from, because two different fallbacks existed for the same concept

Nothing here contacts GitHub or a real model: the review comes from the labelled
deterministic stub, and the changed-path fixtures are throwaway local repositories.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import datetime
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_bundle  # noqa: E402
import lite_cli  # noqa: E402
import lite_errors  # noqa: E402
import lite_fixtures as fx  # noqa: E402
import lite_workflow_check  # noqa: E402


class _FakeResponse:
    """Minimal stand-in for the context manager ``urlopen`` returns."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_contents(raw: bytes, reported_sha: str) -> _FakeResponse:
    """A GitHub `contents` payload carrying ``raw`` but claiming ``reported_sha``."""
    payload = {
        "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
        "sha": reported_sha,
    }
    return _FakeResponse(json.dumps(payload).encode("utf-8"))

#: Three rule sets, deliberately: the defect was that the prompt saw three and the sealed
#: record saw one. Sorted, because the derivation canonicalises the order.
THREE_RULES = "GO_CONSTITUTION,PERMISSION_BOUNDARY,AI_BEHAVIOUR_RULES"
THREE_RULES_SORTED = ["AI_BEHAVIOUR_RULES", "GO_CONSTITUTION", "PERMISSION_BOUNDARY"]
TWO_RULES = "GO_CONSTITUTION,PERMISSION_BOUNDARY"
TWO_RULES_SORTED = ["GO_CONSTITUTION", "PERMISSION_BOUNDARY"]

#: The two changed-path / workflow-identity shapes, as they actually are. BEFORE is the
#: registered form at 7db7b2aa5; AFTER is the fixed one.
BOUNDARY_BEFORE = """jobs:
  j:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with:
          ref: fixture
          path: candidate
          persist-credentials: false
      - name: bind
        run: |
          set -euo pipefail
          git -C candidate diff-tree --no-commit-id --name-only -r HEAD > "$RUNNER_TEMP/changed_paths.txt" || true
          wc -l < "$RUNNER_TEMP/changed_paths.txt"
      - name: freeze
        run: |
          set -euo pipefail
          LITE_WORKFLOW_SHA="$(git rev-parse HEAD:$LITE_WORKFLOW_IDENTITY)"
          {
            echo "LITE_CANDIDATE_SHA=fixture"
          } >> "$GITHUB_ENV"
"""

BOUNDARY_AFTER = """jobs:
  j:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with:
          ref: fixture
          path: candidate
          fetch-depth: 2
          persist-credentials: false
      - name: bind
        run: |
          set -euo pipefail
          git -C candidate diff-tree --no-commit-id --name-only -r --diff-merges=first-parent HEAD | sort -u > "$RUNNER_TEMP/changed_paths.txt"
          test -s "$RUNNER_TEMP/changed_paths.txt"
          wc -l < "$RUNNER_TEMP/changed_paths.txt"
      - name: workflow identity
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          echo "LITE_WORKFLOW_SHA=$(python control-plane/c13-c14-lite/lite_cli.py workflow-identity \\
            --path "$LITE_WORKFLOW_IDENTITY" --ref "${GITHUB_SHA}")" >> "$GITHUB_ENV"
"""


def _boundary_failures(raw: str) -> list:
    failures: list = []
    lite_workflow_check.check_changed_path_boundary("fixture.yml", raw, failures)
    return failures


def _identity_failures(raw: str) -> list:
    failures: list = []
    lite_workflow_check.check_workflow_identity_source("fixture.yml", raw, failures)
    return failures


class ChangedPathBoundaryTests(unittest.TestCase):
    """D-1: the boundary must be right for a merge commit, and must never be silently empty."""

    def test_the_old_shape_is_rejected(self):
        failures = _boundary_failures(BOUNDARY_BEFORE)
        self.assertTrue(failures, "the pre-fix workflow shape must not pass the guard")
        joined = " | ".join(failures)
        self.assertIn("EMPTY for a merge commit", joined)
        self.assertIn("|| true", joined)
        self.assertIn("fetch-depth", joined)

    def test_the_fixed_shape_passes(self):
        self.assertEqual(_boundary_failures(BOUNDARY_AFTER), [])

    def test_a_merge_boundary_must_never_be_empty(self):
        """The exact regression: the workflow command must see the files the merge brought in."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = lite_workflow_check._boundary_fixture(pathlib.Path(tmp))
            argv = ["git", "-C", str(repo), "diff-tree", "--no-commit-id", "--name-only",
                    "-r", "--diff-merges=first-parent", "HEAD"]
            got = sorted(set(subprocess.run(argv, capture_output=True, text=True).stdout.split()))
            self.assertEqual(got, ["f_side.txt"])

            # And the form that was shipped must NOT: this is the defect itself.
            old = ["git", "-C", str(repo), "diff-tree", "--no-commit-id", "--name-only",
                   "-r", "HEAD"]
            before = subprocess.run(old, capture_output=True, text=True)
            self.assertEqual(before.returncode, 0)
            self.assertEqual(before.stdout.strip(), "", "the old form silently printed nothing")

    def test_dash_m_first_parent_is_not_a_fix(self):
        """`-m --first-parent` does not narrow `-m`: the boundary becomes BOTH parents' diffs."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = lite_workflow_check._boundary_fixture(pathlib.Path(tmp))
            argv = ["git", "-C", str(repo), "diff-tree", "--no-commit-id", "--name-only",
                    "-r", "-m", "--first-parent", "HEAD"]
            got = sorted(set(subprocess.run(argv, capture_output=True, text=True).stdout.split()))
            self.assertEqual(got, ["f_mainline.txt", "f_side.txt"])


class WorkflowIdentitySourceTests(unittest.TestCase):
    """D-2: the recorded identity must be the definition that executed."""

    def test_the_old_shape_is_rejected(self):
        failures = _identity_failures(BOUNDARY_BEFORE)
        joined = " | ".join(failures)
        self.assertIn("pinned backend checkout", joined)
        self.assertIn("workflow-identity", joined)

    def test_the_fixed_shape_passes(self):
        self.assertEqual(_identity_failures(BOUNDARY_AFTER), [])

    def test_a_comment_quoting_the_broken_form_is_not_a_defect(self):
        """The fixed workflow explains the bug in a comment; the guard must not fire on it."""
        text = BOUNDARY_AFTER + (
            "          # NOT `git rev-parse HEAD:$LITE_WORKFLOW_IDENTITY`: it points at the\n"
            "          # pinned backend's copy.\n")
        self.assertEqual(_identity_failures(text), [])


class ApplicableRulesSingleSourceTests(unittest.TestCase):
    """D-3: the prompt's rule set and the sealed record's rule set must be the same value."""

    def _env(self, **extra) -> dict:
        now = datetime.datetime.now(datetime.timezone.utc)
        env = {
            "LITE_CANDIDATE_SHA": "a" * 40,
            "LITE_APPLICATION_TREE": "b" * 40,
            "LITE_CELL_PAIR": "C13+C14",
            "LITE_REQUEST_ID": "V70-R3-C13C14-01",
            "LITE_C14_TASK_ID": "V70-R3-C14-01",
            "LITE_C13_TASK_ID": "V70-R3-C13-01",
            "LITE_LEDGER_ROUND_ID": "V70-R3",
            "LITE_NONCE": "defect-fix-nonce",
            "LITE_WORKFLOW_IDENTITY": ".github/workflows/fixture.yml",
            "LITE_WORKFLOW_SHA": "c" * 40,
            "LITE_ISSUED_AT": (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "LITE_EXPIRES_AT": (now + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "LITE_RUN_ID": "1",
            "LITE_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "yuguangzhi3836-glitch/GO",
            # Explicitly empty: "nothing was declared" is a case under test, so it must not
            # depend on whatever the ambient environment happens to hold.
            "LITE_APPLICABLE_RULES": "",
            "LITE_RULE_VERSION": "",
        }
        env.update(extra)
        return env

    def _run(self, argv, env) -> None:
        completed = subprocess.run([sys.executable, str(ROOT / "lite_cli.py"), *argv],
                                   capture_output=True, text=True, env={**os.environ, **env})
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def _seal_a_c14_round(self, tmp: str, env: dict) -> tuple:
        """Drive the CLI exactly the way the workflow does, and return (facts, bundle)."""
        root = pathlib.Path(tmp)
        changed = root / "changed.txt"
        changed.write_text("application/a.py\n", encoding="utf-8")
        scope = root / "scope.json"
        self._run(["scope", "--role", "c14",
                   "--rule", env.get("LITE_APPLICABLE_RULES") or THREE_RULES,
                   "--rule-version", env.get("LITE_RULE_VERSION") or "unversioned",
                   "--changed-paths", str(changed), "--out", str(scope)], env)
        # The spec reads the frozen scope digest from the environment, exactly as the
        # workflow does with its `grep -o '[0-9a-f]\{64\}'` step.
        env = {**env, "LITE_SCOPE_SHA256": json.loads(scope.read_text())["scope_sha256"]}
        spec, facts, contract = root / "spec.json", root / "facts.json", root / "contract.json"
        outcome, bundle = root / "outcome.json", root / "bundle.json"
        self._run(["spec", "--role", "c14", "--spec", str(spec), "--facts", str(facts),
                   "--contract", str(contract)], env)
        self._run(["review", "--spec", str(spec), "--facts", str(facts),
                   "--out", str(outcome), "--stub"], env)
        self._run(["seal", "--spec", str(spec), "--contract", str(contract),
                   "--outcome", str(outcome), "--out", str(bundle)], env)
        return json.loads(facts.read_text()), json.loads(bundle.read_text())

    def test_declared_three_rules_reach_both_the_prompt_and_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts, bundle = self._seal_a_c14_round(tmp, self._env(LITE_APPLICABLE_RULES=THREE_RULES))
            self.assertEqual(facts["applicable_rules"], THREE_RULES_SORTED)
            self.assertEqual(bundle["applicable_rules"], THREE_RULES_SORTED)
            self.assertEqual(sorted(bundle["applicable_rule_versions"]), THREE_RULES_SORTED)

    def test_an_undeclared_rule_set_is_the_same_default_in_both_places(self):
        """The defect in one line: these two used to be 3 rules and 1 rule."""
        with tempfile.TemporaryDirectory() as tmp:
            facts, bundle = self._seal_a_c14_round(tmp, self._env())
            self.assertEqual(facts["applicable_rules"], THREE_RULES_SORTED)
            self.assertEqual(
                bundle["applicable_rules"], facts["applicable_rules"],
                "the sealed record must declare exactly the rule set the prompt was built from")
            self.assertEqual(bundle["applicable_rule_versions"],
                             facts["applicable_rule_versions"])

    def test_a_narrower_declared_rule_set_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts, bundle = self._seal_a_c14_round(tmp, self._env(LITE_APPLICABLE_RULES=TWO_RULES))
            self.assertEqual(facts["applicable_rules"], TWO_RULES_SORTED)
            self.assertEqual(bundle["applicable_rules"], TWO_RULES_SORTED)

    def test_the_default_is_declared_exactly_once(self):
        """A second copy of the default is how the two sides drifted apart."""
        self.assertEqual(sorted(lite_cli.DEFAULT_APPLICABLE_RULES), THREE_RULES_SORTED)
        self.assertEqual(lite_cli.DEFAULT_RULE_VERSION, "unversioned")


class WorkflowIdentityCommandTests(unittest.TestCase):
    """D-2: the helper must compute the value from bytes, and fail closed without one."""

    def test_it_refuses_to_invent_a_value(self):
        """No token means no value - never a plausible-looking fallback."""
        env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
        env["GITHUB_REPOSITORY"] = "yuguangzhi3836-glitch/GO"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "lite_cli.py"), "workflow-identity",
             "--path", ".github/workflows/x.yml", "--ref", "deadbeef"],
            capture_output=True, text=True, env=env)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no token", completed.stderr)

    def test_it_refuses_without_a_repository(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_REPOSITORY")}
        env["GH_TOKEN"] = "irrelevant-because-there-is-no-repository"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "lite_cli.py"), "workflow-identity",
             "--path", ".github/workflows/x.yml", "--ref", "deadbeef"],
            capture_output=True, text=True, env=env)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no repository", completed.stderr)

    def test_a_failed_lookup_is_a_hard_stop(self):
        """An unreachable ref must fail the step, not yield a partial or guessed value.

        Offline on purpose: ``urlopen`` is stubbed, so this suite never contacts GitHub.
        """
        import urllib.error
        import urllib.request

        args = argparse.Namespace(path=".github/workflows/x.yml", ref="deadbeef",
                                  repository="yuguangzhi3836-glitch/GO")
        with mock.patch.dict(os.environ, {"GH_TOKEN": "stub"}, clear=False):
            with mock.patch.object(
                    urllib.request, "urlopen",
                    side_effect=urllib.error.HTTPError("u", 404, "Not Found", {}, None)):
                with self.assertRaises(SystemExit) as caught:
                    lite_cli.cmd_workflow_identity(args)
        self.assertIn("HTTP 404", str(caught.exception))

    def test_the_reported_blob_sha_must_match_the_returned_bytes(self):
        """The value is computed from the content, never taken on the API's word."""
        import urllib.request

        raw = b"name: fixture\n"
        args = argparse.Namespace(path=".github/workflows/x.yml", ref="deadbeef",
                                  repository="yuguangzhi3836-glitch/GO")
        honest = _fake_contents(raw, lite_cli._git_blob_sha(raw))
        lying = _fake_contents(raw, "0" * 40)
        with mock.patch.dict(os.environ, {"GH_TOKEN": "stub"}, clear=False):
            with mock.patch.object(urllib.request, "urlopen", return_value=honest):
                with contextlib.redirect_stdout(io.StringIO()) as printed:
                    self.assertEqual(lite_cli.cmd_workflow_identity(args), 0)
            self.assertEqual(printed.getvalue().strip(), lite_cli._git_blob_sha(raw))
            with mock.patch.object(urllib.request, "urlopen", return_value=lying):
                with self.assertRaises(SystemExit) as caught:
                    lite_cli.cmd_workflow_identity(args)
        self.assertIn("does not match the returned bytes", str(caught.exception))

    def test_the_blob_sha_is_git_compatible(self):
        """The value must be a git blob SHA, so it can be compared with `git hash-object`.

        Run inside a throwaway repository rather than the checkout: this worktree's
        ``.git`` file holds a Windows ``gitdir:`` path, so git cannot open it from Linux,
        and ``check=True`` is deliberate - the first version of this test compared against
        an empty string produced by that failure and reported a misleading assertion.
        """
        raw = b"name: fixture\n"
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True, capture_output=True)
            expected = subprocess.run(["git", "-C", tmp, "hash-object", "--stdin"],
                                      input=raw, capture_output=True, check=True)
        self.assertEqual(lite_cli._git_blob_sha(raw), expected.stdout.decode().strip())


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# D-4 part one: what a non-pass verdict must carry
# ---------------------------------------------------------------------------

class BlockedVerdictSemanticsTests(unittest.TestCase):
    """D-4: a non-pass verdict must carry evidence, and must never impersonate a provider failure.

    Before the fix, `validate_c14` demanded a `failure_class` for both FAIL and BLOCKED, while
    the opinion schema let the model return those verdicts itself. A model-authored BLOCKED was
    therefore unsealable, and because the opinion had not been published yet, run 36148838395
    died at the seal and took the only copy of the reviewer's reasoning with it.
    """

    def _record(self, **changes):
        record = copy.deepcopy(fx.make_round()["c14_bundle"])
        record.update(changes)
        return record

    def test_the_unmodified_fixture_record_is_valid(self):
        """Guard the whole class against a base record that never validated in the first place."""
        lite_bundle.validate_c14(copy.deepcopy(fx.make_round()["c14_bundle"]))

    # A - provider / quota / transport failure: BLOCKED, and it must name its class.
    def test_a_provider_failure_names_its_failure_class(self):
        lite_bundle.validate_c14(self._record(
            verdict="BLOCKED", failure_class="AI_QUOTA_EXHAUSTED", blocking_issues=[]))

    # B - the AI reviewed normally and blocked: no provider class, but it must give reasons.
    def test_a_model_authored_blocked_is_sealable_with_its_reasons(self):
        lite_bundle.validate_c14(self._record(
            verdict="BLOCKED", failure_class=None,
            blocking_issues=["the change surface is entirely outside application/"]))

    # C - the same, with nothing to show for it.
    def test_a_model_authored_blocked_without_reasons_is_refused(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_bundle.validate_c14(self._record(
                verdict="BLOCKED", failure_class=None, blocking_issues=[]))
        self.assertEqual(ctx.exception.reason, "c14_model_blocked_without_blocking_issues")

    # D - a pass may not carry blocking issues.
    def test_a_pass_scoped_with_blocking_issues_is_refused(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_bundle.validate_c14(self._record(
                verdict="PASS_SCOPED", failure_class=None, blocking_issues=["something"]))
        self.assertEqual(ctx.exception.reason, "c14_pass_with_blocking_issues")

    def test_a_pass_scoped_without_remediation_closure_is_refused(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_bundle.validate_c14(self._record(
                verdict="PASS_SCOPED", failure_class=None, blocking_issues=[],
                remediation_status="OPEN"))
        self.assertEqual(ctx.exception.reason, "c14_pass_without_remediation_closure")

    # A FAIL needs evidence, and must NOT be forced to fabricate a provider class.
    def test_a_fail_with_a_blocking_finding_needs_no_failure_class(self):
        lite_bundle.validate_c14(self._record(
            verdict="FAIL", failure_class=None, blocking_issues=[],
            findings=[{"id": "F-1", "severity": "BLOCKER", "statement": "breaks the rule"}]))

    def test_a_fail_with_a_blocking_issue_needs_no_failure_class(self):
        lite_bundle.validate_c14(self._record(
            verdict="FAIL", failure_class=None, blocking_issues=["unpermitted permission"],
            findings=[]))

    def test_a_fail_without_any_evidence_is_refused(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_bundle.validate_c14(self._record(
                verdict="FAIL", failure_class=None, blocking_issues=[],
                findings=[{"id": "F-1", "severity": "INFO", "statement": "just a note"}]))
        self.assertEqual(ctx.exception.reason, "c14_fail_without_findings_or_blocking_issues")

    def test_the_rule_that_killed_run_36148838395_is_gone(self):
        """Explicit marker: the old refusal code must not come back."""
        source = (ROOT / "lite_bundle.py").read_text(encoding="utf-8")
        self.assertNotIn("c14_non_pass_requires_failure_class", source)


# ---------------------------------------------------------------------------
# D-4 part two: the raw record must survive a refused seal
# ---------------------------------------------------------------------------

class RawEvidencePreservationTests(unittest.TestCase):
    """A refused seal used to leave nothing behind but a red job."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def _args(self, out, **paths):
        base = {"spec": None, "facts": None, "contract": None, "outcome": None, "scope": None,
                "seal_result": None, "seal_stdout": None, "seal_stderr": None}
        base.update(paths)
        return argparse.Namespace(out=out, **base)

    def _write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_the_raw_record_is_kept_when_the_seal_refused(self):
        out = self.root / "raw"
        args = self._args(
            str(out),
            contract=self._write("c14.contract.json", '{"candidate_commit_sha": "abc"}'),
            outcome=self._write("c14.outcome.json", '{"verdict": "BLOCKED", "summary": "why"}'),
            seal_result=self._write(
                "seal_result.json", '{"step": "seal", "status": "REFUSED", "exit_code": 2}'))
        self.assertEqual(lite_cli.cmd_raw_evidence(args), 0)

        manifest = json.loads((out / "raw_evidence_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(entry["name"] for entry in manifest["files"]),
                         ["contract", "outcome", "seal_result"])
        self.assertEqual(manifest["seal_status"]["status"], "REFUSED")
        self.assertIs(manifest["sealed_bundle_published_by_this_step"], False)
        self.assertIs(manifest["authorizes_any_action"], False)
        for entry in manifest["files"]:
            raw = (out / entry["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"], entry["file"])

    def test_a_step_that_never_ran_leaves_a_gap_not_an_exception(self):
        """If the producing step failed, the record must still ship, with the gap named.

        The paths are passed exactly as the workflow passes them - the difference is that the
        files were never written, which is what a failed upstream step looks like.
        """
        out = self.root / "raw"

        def never_written(name):
            return str(self.root / name)

        args = self._args(str(out),
                          spec=never_written("c14.spec.json"),
                          facts=never_written("c14.facts.json"),
                          contract=never_written("c14.contract.json"),
                          outcome=never_written("c14.outcome.json"),
                          scope=never_written("scope.json"),
                          seal_result=self._write("seal_result.json", '{"status": "REFUSED"}'))
        self.assertEqual(lite_cli.cmd_raw_evidence(args), 0)
        manifest = json.loads((out / "raw_evidence_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["name"] for entry in manifest["files"]], ["seal_result"])
        self.assertEqual(sorted(manifest["missing"]),
                         ["contract", "facts", "outcome", "scope", "spec"])

    def test_a_path_that_was_not_asked_for_is_not_reported_as_missing(self):
        """'not requested' must not be dressed up as 'lost' - the manifest has to stay honest."""
        out = self.root / "raw"
        args = self._args(str(out),
                          seal_result=self._write("seal_result.json", '{"status": "SEALED"}'))
        self.assertEqual(lite_cli.cmd_raw_evidence(args), 0)
        manifest = json.loads((out / "raw_evidence_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["missing"], [])

    def test_a_credential_shape_is_refused_before_anything_is_written(self):
        out = self.root / "raw"
        # Split on purpose: writing the literal in one piece would make this file itself match
        # the repository's own secret scan.
        fake_key = "sk-" + "A1b2C3d4E5f6G7h8I9j0"
        args = self._args(
            str(out),
            contract=self._write("c14.contract.json", '{"clean": true}'),
            outcome=self._write("c14.outcome.json", '{"summary": "%s"}' % fake_key))
        with self.assertRaises(SystemExit) as ctx:
            lite_cli.cmd_raw_evidence(args)
        self.assertIn("openai_key", str(ctx.exception))
        # scan-before-write: the clean contract must not be on disk either, and the output
        # directory must not have been created at all.
        self.assertFalse(out.exists())

    def test_a_private_key_block_is_refused(self):
        out = self.root / "raw"
        args = self._args(str(out), outcome=self._write(
            "c14.outcome.json", '{"x": "-----BEGIN ' + 'PRIVATE KEY-----"}'))
        with self.assertRaises(SystemExit) as ctx:
            lite_cli.cmd_raw_evidence(args)
        self.assertIn("private_key_block", str(ctx.exception))

    def test_a_clean_run_reports_no_missing_files(self):
        out = self.root / "raw"
        args = self._args(str(out),
                          spec=self._write("c14.spec.json", '{"role": "c14"}'),
                          facts=self._write("c14.facts.json", '{"cell_id": "C14"}'),
                          contract=self._write("c14.contract.json", '{"cell_id": "C14"}'),
                          outcome=self._write("c14.outcome.json", '{"verdict": "PASS_SCOPED"}'),
                          scope=self._write("scope.json", '{"scope_sha256": "x"}'),
                          seal_result=self._write("seal_result.json", '{"status": "SEALED"}'))
        self.assertEqual(lite_cli.cmd_raw_evidence(args), 0)
        manifest = json.loads((out / "raw_evidence_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["missing"], [])
        self.assertEqual(len(manifest["files"]), 6)


_SEALED_ARTIFACT = "          name: c13c14-lite-c14-" + "${{ inputs.candidate_sha }}"
_RAW_ARTIFACT = "          name: c13c14-lite-c14-raw-" + "${{ inputs.candidate_sha }}"

WORKFLOW_WITHOUT_RAW_STEPS = """name: synthetic
on:
  workflow_dispatch:
    inputs:
      candidate_sha: {required: true}
permissions:
  contents: read
  actions: read
jobs:
  j:
    runs-on: ubuntu-24.04
    steps:
      - name: Seal
        run: python lite_cli.py seal --out "$RUNNER_TEMP/artifacts/c14_bundle.json"
      - name: Publish the sealed C14 bundle
        if: always()
        uses: actions/upload-artifact@v4
        with:
""" + _SEALED_ARTIFACT + """
          path: ${{ runner.temp }}/artifacts
          retention-days: 90
"""

WORKFLOW_WITH_RAW_STEPS = """name: synthetic
on:
  workflow_dispatch:
    inputs:
      candidate_sha: {required: true}
permissions:
  contents: read
  actions: read
jobs:
  j:
    runs-on: ubuntu-24.04
    steps:
      - name: Seal
        run: python lite_cli.py seal --out "$RUNNER_TEMP/artifacts/c14_bundle.json"
      - name: Preserve the raw review evidence whatever the seal decided
        if: always()
        run: |
          python lite_cli.py raw-evidence --out "$RUNNER_TEMP/raw" --outcome "$RUNNER_TEMP/c14.outcome.json" --contract "$RUNNER_TEMP/c14.contract.json" --seal-result "$RUNNER_TEMP/seal_result.json"
      - name: Publish the raw review evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
""" + _RAW_ARTIFACT + """
          path: ${{ runner.temp }}/raw
          retention-days: 90
      - name: Publish the sealed C14 bundle
        uses: actions/upload-artifact@v4
        with:
""" + _SEALED_ARTIFACT + """
          path: ${{ runner.temp }}/artifacts
          retention-days: 90
"""


class RawEvidenceWorkflowTests(unittest.TestCase):
    """The requirement has to hold in the shipped YAML, not only in the helper."""

    def _check(self, text):
        failures: list = []
        lite_workflow_check.check_raw_evidence_survives_a_refused_seal(
            lite_workflow_check.C14_WORKFLOW, text, failures)
        return failures

    def test_the_shipped_c14_workflow_satisfies_it(self):
        text = (pathlib.Path(lite_workflow_check.WORKFLOW_DIR)
                / lite_workflow_check.C14_WORKFLOW).read_text(encoding="utf-8")
        self.assertEqual(self._check(text), [])

    def test_the_check_bites_without_the_raw_steps(self):
        joined = " | ".join(self._check(WORKFLOW_WITHOUT_RAW_STEPS))
        self.assertIn("raw-evidence", joined)
        self.assertIn("must not be published unconditionally", joined)

    def test_the_fixed_shape_passes(self):
        self.assertEqual(self._check(WORKFLOW_WITH_RAW_STEPS), [])

    def test_a_raw_step_that_is_not_always_is_refused(self):
        text = WORKFLOW_WITH_RAW_STEPS.replace(
            "      - name: Preserve the raw review evidence whatever the seal decided\n"
            "        if: always()\n",
            "      - name: Preserve the raw review evidence whatever the seal decided\n")
        self.assertNotEqual(text, WORKFLOW_WITH_RAW_STEPS)
        self.assertIn("if: always()", " | ".join(self._check(text)))

    def test_c13_is_not_asked_for_a_step_it_does_not_need(self):
        """C13's always-run verify step already preserves its opinion; do not invent a rule."""
        failures: list = []
        lite_workflow_check.check_raw_evidence_survives_a_refused_seal(
            lite_workflow_check.C13_WORKFLOW, WORKFLOW_WITHOUT_RAW_STEPS, failures)
        self.assertEqual(failures, [])
