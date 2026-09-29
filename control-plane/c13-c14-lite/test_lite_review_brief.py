"""The review brief: does the reviewer know which task it is grading?

Two real failures are being closed here, and they are the same failure seen from two sides.

1. C13 and C14 were both handed the *answer* - the frozen change surface, the candidate's own
   first-parent diff, the rule text, the machine evidence - and neither was handed the
   *question*. A reviewer that only sees the answer grades against its own idea of best
   practice, which is how a candidate that met its task gets sent back for things the task never
   asked for.
2. Nothing in the prompt said a clean review was an acceptable outcome. A model asked to find
   problems will find them, and a MINOR observation then reads like a requirement.

So: the brief is the candidate's own pull request, frozen as GitHub's raw facts and matched
deterministically (``head.sha == candidate`` or ``merge_commit_sha == candidate``, unique or
refuse), and both cells receive it. The verdict vocabulary is unchanged; PASS_SCOPED now has a
stated meaning - acceptable, not perfect.

Everything here runs offline. The HTTP reader is injected, because a test that needs the network
is a test that fails for the wrong reason.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

import lite_ai_reviewer
import lite_fixtures as fx
import lite_review_brief
import lite_workflow_check

ROOT = pathlib.Path(__file__).resolve().parent

CANDIDATE = "a" * 40
OTHER_CANDIDATE = "b" * 40
CHANGED = ("application/a.py", "application/b.py")
SYNTHETIC_CANDIDATE_DIFF = (
    "diff --git a/application/a.py b/application/a.py\n"
    "+frozen candidate content\n"
)
SYNTHETIC_MACHINE_INVENTORY = "application/tests"

#: A token-shaped literal, to prove it never reaches a recorded artefact.
FAKE_TOKEN = "ghp_" + "A" * 24


def pull_request(number, *, head_sha=None, merge_sha=None, title="Synthetic task",
                 body="Synthetic body: do the thing.\n"):
    """One GitHub-shaped pull request, as the commit -> pull requests API reports it."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": "closed",
        "merged_at": "2026-09-26T00:00:00Z",
        "merge_commit_sha": merge_sha,
        "html_url": f"https://github.com/{fx.REPOSITORY}/pull/{number}",
        "base": {"ref": "main"},
        "head": {"ref": f"synthetic/head-{number}", "sha": head_sha},
    }


class ReviewBriefResolutionTests(unittest.TestCase):
    """Deterministic matching. A guess here grades the wrong task, which is worse than refusing."""

    def test_a_pr_head_sha_resolves_to_that_pull_request(self):
        pulls = [pull_request(11, head_sha=CANDIDATE), pull_request(12, head_sha=OTHER_CANDIDATE)]
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: pulls)
        self.assertEqual(record["status"], "OK", record)
        self.assertEqual(record["matched_by"], lite_review_brief.MATCHED_BY_HEAD)
        self.assertEqual(record["pull_request"]["number"], 11)

    def test_a_merged_candidates_merge_commit_sha_resolves_to_that_pull_request(self):
        pulls = [
            pull_request(21, head_sha=OTHER_CANDIDATE),
            pull_request(22, head_sha=OTHER_CANDIDATE, merge_sha=CANDIDATE),
        ]
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: pulls)
        self.assertEqual(record["status"], "OK", record)
        self.assertEqual(record["matched_by"], lite_review_brief.MATCHED_BY_MERGE)
        self.assertEqual(record["pull_request"]["number"], 22)

    def test_zero_matches_is_refused(self):
        pulls = [pull_request(31, head_sha=OTHER_CANDIDATE)]
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: pulls)
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["reason"], lite_review_brief.PR_NOT_FOUND)
        self.assertIsNone(record["pull_request"])
        self.assertTrue(record["blocking_issues"])

    def test_two_matching_pull_requests_are_refused_as_ambiguous(self):
        pulls = [pull_request(41, head_sha=CANDIDATE), pull_request(42, head_sha=CANDIDATE)]
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: pulls)
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["reason"], lite_review_brief.PR_AMBIGUOUS)
        self.assertIn("41", record["detail"])
        self.assertIn("42", record["detail"])

    def test_a_head_match_next_to_a_merge_match_is_ambiguous_not_resolved(self):
        """Two different tasks are two different tasks; neither wins by being 'first'."""
        pulls = [
            pull_request(51, head_sha=CANDIDATE),
            pull_request(52, head_sha=OTHER_CANDIDATE, merge_sha=CANDIDATE),
        ]
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: pulls)
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["reason"], lite_review_brief.PR_AMBIGUOUS)

    def test_the_same_pull_request_twice_is_not_an_ambiguity(self):
        pulls = [pull_request(61, head_sha=CANDIDATE), pull_request(61, head_sha=CANDIDATE)]
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: pulls)
        self.assertEqual(record["status"], "OK", record)
        self.assertEqual(record["pull_request"]["number"], 61)

    def test_a_lookup_failure_is_refused_and_never_guessed(self):
        def explode(sha):
            raise lite_review_brief.BriefFetchFailed("commits/%s/pulls" % sha, status=500,
                                                     detail="HTTP 500")

        record = lite_review_brief.resolve(CANDIDATE, explode)
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["reason"], lite_review_brief.PR_UNREADABLE)

    def test_a_full_page_is_refused_because_uniqueness_cannot_be_established(self):
        pulls = [pull_request(70 + index, head_sha=OTHER_CANDIDATE)
                 for index in range(lite_review_brief.PAGE_SIZE)]
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: pulls)
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["reason"], lite_review_brief.PR_AMBIGUOUS)

    def test_an_invalid_candidate_sha_is_refused(self):
        record = lite_review_brief.resolve("not-a-sha", lambda sha: [])
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["reason"], lite_review_brief.PR_INVALID)

    def test_the_brief_carries_only_githubs_own_frozen_facts(self):
        only = pull_request(81, head_sha=CANDIDATE, title="Real title", body="Real body")
        record = lite_review_brief.resolve(CANDIDATE, lambda sha: [only])
        brief = record["pull_request"]
        self.assertEqual(set(brief), set(lite_review_brief.BRIEF_FIELDS) | {"matched_by"})
        self.assertEqual(brief["number"], 81)
        self.assertEqual(brief["title"], "Real title")
        self.assertEqual(brief["body"], "Real body")
        self.assertEqual(brief["head_sha"], CANDIDATE)
        self.assertEqual(brief["base_ref"], "main")
        self.assertEqual(brief["state"], "closed")
        # The URL is navigation, and it is recorded as navigation only - nothing is verified
        # through it and it is not an authority.
        self.assertEqual(brief["html_url"], f"https://github.com/{fx.REPOSITORY}/pull/81")


class _SpecRoundMixin:
    """Drive ``spec`` exactly the way the workflow does, with a brief on disk beside it."""

    def _env(self, directory, rule_input, **extra):
        now = datetime.datetime.now(datetime.timezone.utc)
        env = {
            "LITE_CANDIDATE_SHA": CANDIDATE,
            "LITE_APPLICATION_TREE": "b" * 40,
            "LITE_CELL_PAIR": "C13+C14",
            "LITE_REQUEST_ID": "V70-R3-C13C14-02",
            "LITE_C14_TASK_ID": "V70-R3-C14-02",
            "LITE_C13_TASK_ID": "V70-R3-C13-02",
            "LITE_LEDGER_ROUND_ID": "V70-R3",
            "LITE_NONCE": "ccv1-review-brief-0001",
            "LITE_WORKFLOW_IDENTITY": ".github/workflows/c14-rule-compliance.yml",
            "LITE_WORKFLOW_SHA": "c" * 40,
            "LITE_ISSUED_AT": (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "LITE_EXPIRES_AT": (now + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "LITE_RUN_ID": "1",
            "LITE_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": fx.REPOSITORY,
            "LITE_RULE_INPUT": str(rule_input),
        }
        env.update(extra)
        return env

    def _cli(self, argv, env):
        return subprocess.run([sys.executable, str(ROOT / "lite_cli.py"), *argv],
                              capture_output=True, text=True, env={**os.environ, **env})

    def _run(self, argv, env):
        completed = self._cli(argv, env)
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        return completed

    def _freeze(self, root, role, *, criteria=(), inventory=None, brief=None, brief_sha=CANDIDATE):
        """A frozen scope, a candidate diff and a resolved review brief, on disk."""
        rule_input = root / "rule_input.json"
        rule_input.write_text(json.dumps(fx.rule_input_record()), encoding="utf-8")
        changed = root / "changed_paths.txt"
        changed.write_text("".join(f"{line}\n" for line in CHANGED), encoding="utf-8")
        candidate_diff = root / "candidate.diff"
        candidate_diff.write_text(SYNTHETIC_CANDIDATE_DIFF, encoding="utf-8")
        brief_path = root / "review_brief.json"
        if brief is not None:
            brief_path.write_text(json.dumps(brief, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            fx.write_review_brief(brief_path, brief_sha)
        env = self._env(root, rule_input)
        argv = ["scope", "--role", role, "--changed-paths", str(changed)]
        if inventory is not None:
            inventory_file = root / "test_inventory.txt"
            inventory_file.write_text("".join(f"{line}\n" for line in inventory), encoding="utf-8")
            argv += ["--inventory", str(inventory_file)]
        for criterion in criteria:
            argv += ["--criterion", criterion]
        if role == "c14":
            argv += ["--rule-input", str(rule_input)]
        scope_path = root / "scope.json"
        self._run(argv + ["--out", str(scope_path)], env)
        env = {**env, "LITE_SCOPE_SHA256":
               json.loads(scope_path.read_text(encoding="utf-8"))["scope_sha256"]}
        return env, scope_path, candidate_diff, brief_path

    def _spec_argv(self, role, root, scope_path, candidate_diff, brief_path, *,
                   manifest=None, junit=None):
        argv = ["spec", "--role", role,
                "--scope", str(scope_path),
                "--candidate-diff", str(candidate_diff),
                "--review-brief", str(brief_path),
                "--spec", str(root / f"{role}.spec.json"),
                "--facts", str(root / f"{role}.facts.json"),
                "--contract", str(root / f"{role}.contract.json")]
        if manifest is not None:
            argv += ["--machine-manifest", str(manifest)]
        if junit is not None:
            argv += ["--junit", str(junit)]
        return argv

    def _facts(self, root, role):
        return json.loads((root / f"{role}.facts.json").read_text(encoding="utf-8"))

    def _synthetic_machine_files(self, root):
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({
            "inventory": SYNTHETIC_MACHINE_INVENTORY,
            "postgres_version": "18.4",
            "docker_used": True,
            "junit_sha256": "synthetic",
            "stdout_sha256": "synthetic",
            "candidate_sha": CANDIDATE,
            "application_tree": "b" * 40,
        }), encoding="utf-8")
        junit = root / "junit.xml"
        junit.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<testsuites><testsuite name="s" tests="305" failures="0" errors="0" skipped="0" />'
            "</testsuites>\n", encoding="utf-8")
        return manifest, junit


class ReviewBriefInFactsTests(_SpecRoundMixin, unittest.TestCase):
    """Both cells must actually receive the task, and the refusal must be fail-closed."""

    def test_the_c14_facts_and_prompt_carry_the_review_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, scope_path, diff_path, brief_path = self._freeze(root, "c14")
            self._run(self._spec_argv("c14", root, scope_path, diff_path, brief_path), env)
            facts = self._facts(root, "c14")
            self.assertEqual(facts["review_brief"]["number"], fx.REVIEW_BRIEF_PR_NUMBER)
            self.assertEqual(facts["review_brief"]["head_sha"], CANDIDATE)
            prompt = lite_ai_reviewer.build_prompt("c14", facts)
            self.assertIn(fx.REVIEW_BRIEF_TITLE, prompt)
            self.assertIn(fx.REVIEW_BRIEF_BODY.strip(), prompt)

    def test_the_c13_facts_and_prompt_carry_the_review_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, scope_path, diff_path, brief_path = self._freeze(
                root, "c13", criteria=["every required negative case refuses"],
                inventory=[SYNTHETIC_MACHINE_INVENTORY])
            manifest, junit = self._synthetic_machine_files(root)
            self._run(self._spec_argv("c13", root, scope_path, diff_path, brief_path,
                                      manifest=manifest, junit=junit), env)
            facts = self._facts(root, "c13")
            self.assertEqual(facts["review_brief"]["number"], fx.REVIEW_BRIEF_PR_NUMBER)
            prompt = lite_ai_reviewer.build_prompt("c13", facts)
            self.assertIn(fx.REVIEW_BRIEF_TITLE, prompt)

    def test_changing_the_brief_changes_the_facts_and_input_digest(self):
        """The brief is bound by the existing facts digest - no second registry needed."""
        digests = []
        for body in ("First body.\n", "Second body, a different task.\n"):
            with tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                brief = fx.review_brief_record(CANDIDATE)
                brief["pull_request"]["body"] = body
                env, scope_path, diff_path, brief_path = self._freeze(root, "c14", brief=brief)
                self._run(self._spec_argv("c14", root, scope_path, diff_path, brief_path), env)
                outcome = root / "outcome.json"
                self._run(["review", "--spec", str(root / "c14.spec.json"),
                           "--facts", str(root / "c14.facts.json"),
                           "--out", str(outcome), "--stub"], env)
                digests.append(json.loads(outcome.read_text(encoding="utf-8"))["input_sha256"])
                self.assertEqual(self._facts(root, "c14")["review_brief"]["body"], body)
        self.assertNotEqual(digests[0], digests[1])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in digests))

    def test_a_round_with_no_resolvable_brief_is_refused_before_the_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            refused = lite_review_brief.resolve(
                CANDIDATE, lambda sha: [pull_request(91, head_sha=OTHER_CANDIDATE)])
            self.assertEqual(refused["status"], "BLOCKED")
            env, scope_path, diff_path, brief_path = self._freeze(root, "c14", brief=refused)
            completed = self._cli(
                self._spec_argv("c14", root, scope_path, diff_path, brief_path), env)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("no review brief", completed.stderr)
            self.assertIn(lite_review_brief.PR_NOT_FOUND, completed.stderr)

    def test_a_brief_for_another_candidate_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, scope_path, diff_path, brief_path = self._freeze(root, "c14", brief_sha=OTHER_CANDIDATE)
            completed = self._cli(
                self._spec_argv("c14", root, scope_path, diff_path, brief_path), env)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("does not belong to the frozen candidate", completed.stderr)

    def test_no_credential_reaches_the_recorded_facts_or_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, scope_path, diff_path, brief_path = self._freeze(root, "c14", brief_sha=CANDIDATE)
            self._run(self._spec_argv("c14", root, scope_path, diff_path, brief_path),
                      {**env, "GH_TOKEN": FAKE_TOKEN, "GITHUB_TOKEN": FAKE_TOKEN})
            for name in ("c14.facts.json", "c14.spec.json", "c14.contract.json", "review_brief.json"):
                raw = (root / name).read_text(encoding="utf-8")
                self.assertNotIn(FAKE_TOKEN, raw, name)
                self.assertIsNone(re.search(r"gh[pousr]_[A-Za-z0-9]{16,}", raw), name)
                self.assertNotIn("Authorization", raw, name)


class ReviewerStandardTests(unittest.TestCase):
    """The prompt must say what a verdict means, or 'acceptable' silently becomes 'perfect'."""

    #: The five semantics the convergence depends on, asserted as substrings that cannot be
    #: satisfied by a reworded prompt that dropped the meaning.
    REQUIRED = (
        "acceptance, not perfection",
        "Do not invent requirements outside",
        "Finding nothing blocking is a valid and successful review result",
        "do not require rework",
        "Rework is justified only by a real blocking defect",
        "Do not manufacture findings",
    )

    def test_both_roles_receive_the_shared_standard(self):
        for role in ("c13", "c14"):
            prompt = lite_ai_reviewer.build_prompt(role, fx.role_facts(role))
            for expected in self.REQUIRED:
                self.assertIn(expected, prompt, f"{role}: {expected}")

    def test_passing_findings_may_coexist_with_pass_scoped(self):
        for role in ("c13", "c14"):
            prompt = lite_ai_reviewer.build_prompt(role, fx.role_facts(role))
            self.assertIn("PASS_SCOPED may include non-blocking findings and remaining risks",
                          prompt)

    def test_c14_is_told_it_is_not_a_github_process_checker(self):
        prompt = lite_ai_reviewer.build_prompt("c14", fx.role_facts("c14"))
        self.assertIn("You are not a second GitHub process checker", prompt)
        for mechanical in ("short-lived branch exists", "how many reviews a pull",
                           "CI/check status", "template field", "metadata"):
            self.assertIn(mechanical, prompt, mechanical)
        # ...and it must still judge whether the brief's own claim is true of the change.
        self.assertIn("that inconsistency is a real governance finding", prompt)

    def test_c14_keeps_deferred_release_gates_out_of_candidate_blockers(self):
        prompt = lite_ai_reviewer.build_prompt("c14", fx.role_facts("c14"))
        for expected in (
            "STAGE BOUNDARY",
            "the review brief defines what this candidate claims to complete at this review stage",
            "cannot waive an applicable rule",
            "remaining gates",
            "later operational verification",
            "MUST NOT by themselves cause FAIL or BLOCKED",
            "the current implementation remains fail-closed",
            "PASS_SCOPED is allowed",
            "missing evidence that the brief intentionally defers",
            "downstream release/operational gate",
        ):
            self.assertIn(expected, prompt, expected)

    def test_c14_stage_boundary_does_not_hide_current_rule_violations(self):
        prompt = lite_ai_reviewer.build_prompt("c14", fx.role_facts("c14"))
        self.assertIn("FAIL requires a current-stage rule violation", prompt)
        self.assertIn("false claim that a deferred requirement is complete", prompt)
        self.assertIn("actually enables or authorizes the operation", prompt)
        self.assertIn("the issue is no longer downstream and may block", prompt)

    def test_c14_pass_scoped_matches_the_existing_seal_contract(self):
        prompt = lite_ai_reviewer.build_prompt("c14", fx.role_facts("c14"))
        for expected in (
            "VERDICT/REMEDIATION CONSISTENCY",
            "when your verdict is PASS_SCOPED",
            "blocking_issues must be empty",
            "remediation_status MUST be NOT_REQUIRED",
            "or CLOSED if previously blocking remediation has been fully completed",
            "Never return PASS_SCOPED with OPEN or PARTIAL",
        ):
            self.assertIn(expected, prompt, expected)

    def test_c14_open_or_partial_means_pass_scoped_is_inconsistent(self):
        prompt = lite_ai_reviewer.build_prompt("c14", fx.role_facts("c14"))
        self.assertIn(
            "OPEN/PARTIAL means blocking remediation is still outstanding",
            prompt,
        )
        self.assertIn("inconsistent with PASS_SCOPED", prompt)

    def test_c13_is_told_minor_improvements_are_not_failures(self):
        prompt = lite_ai_reviewer.build_prompt("c13", fx.role_facts("c13"))
        self.assertIn("These are not failures and must not be turned into a non-PASS verdict",
                      prompt)
        self.assertIn("quality_findings or remaining_risks", prompt)
        self.assertIn("an original task objective the candidate did not meet", prompt)

    def test_the_standard_did_not_add_an_output_field(self):
        """The convergence is a prompt change: no score, no new schema key."""
        for schema in (lite_ai_reviewer.C14_OUTPUT_SCHEMA, lite_ai_reviewer.C13_OUTPUT_SCHEMA):
            self.assertNotIn("score", json.dumps(schema))
            self.assertNotIn("points", json.dumps(schema))
            self.assertNotIn("threshold", json.dumps(schema))


class ReviewBriefWorkflowGuardTests(unittest.TestCase):
    """The structural half: an edit that drops the brief must fail review, not a red run."""

    TEMPLATE = (
        "name: x\n"
        "jobs:\n"
        "  review:\n"
        "    steps:\n"
        "      - name: Resolve the review brief\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "{brief}"
        "      - name: Build the frozen candidate contract\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          python control-plane/c13-c14-lite/lite_cli.py spec --role c14 \\\n"
        "            --scope \"$RUNNER_TEMP/scope.json\" \\\n"
        "            --candidate-diff \"$RUNNER_TEMP/candidate.diff\" \\\n"
        "            --review-brief \"$RUNNER_TEMP/review_brief.json\" \\\n"
        "            --spec \"$RUNNER_TEMP/x.spec.json\"\n"
    )

    BRIEF_BLOCK = (
        "          python control-plane/c13-c14-lite/lite_cli.py review-brief \\\n"
        "            --candidate-sha \"${{ inputs.candidate_sha }}\" \\\n"
        "            --out \"$RUNNER_TEMP/review_brief.json\"\n"
    )

    def failures(self, *, brief=None, spec_flags=None):
        raw = self.TEMPLATE.format(brief=self.BRIEF_BLOCK if brief is None else brief)
        if spec_flags is not None:
            raw = raw.replace("            --review-brief \"$RUNNER_TEMP/review_brief.json\" \\\n",
                              spec_flags)
        out = []
        lite_workflow_check.check_review_brief_is_resolved_read_only(
            lite_workflow_check.C14_WORKFLOW, raw, out)
        lite_workflow_check.check_spec_carries_the_frozen_review_content(
            lite_workflow_check.C14_WORKFLOW, raw, out)
        return " | ".join(out)

    def test_the_shipped_workflows_pass(self):
        for name in lite_workflow_check.PRODUCTION_WORKFLOWS:
            raw = (lite_workflow_check.WORKFLOW_DIR / name).read_text(encoding="utf-8")
            failures = []
            lite_workflow_check.check_review_brief_is_resolved_read_only(name, raw, failures)
            lite_workflow_check.check_spec_carries_the_frozen_review_content(name, raw, failures)
            self.assertEqual(failures, [], name)

    def test_dropping_the_review_brief_argument_is_caught(self):
        self.assertIn("--review-brief", self.failures(spec_flags="            \\\n"))

    def test_dropping_the_resolver_step_is_caught(self):
        self.assertIn("lite_cli.py review-brief", self.failures(brief=""))

    def test_dropping_the_candidate_sha_from_the_resolver_is_caught(self):
        block = self.BRIEF_BLOCK.replace("            --candidate-sha \"${{ inputs.candidate_sha }}\" \\\n", "")
        self.assertIn("candidate SHA", self.failures(brief=block))

    def test_writing_somewhere_else_is_caught(self):
        block = self.BRIEF_BLOCK.replace("$RUNNER_TEMP/review_brief.json", "$RUNNER_TEMP/elsewhere.json")
        self.assertIn("review_brief.json", self.failures(brief=block))


if __name__ == "__main__":
    unittest.main()
