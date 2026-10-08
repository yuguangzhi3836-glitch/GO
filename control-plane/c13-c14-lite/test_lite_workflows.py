"""Workflow and schema contract checks, run offline as part of the suite.

These do not prove a workflow *ran*; they prove the shipped YAML is dispatchable,
least-privileged, credential-separated and consistent with the code that consumes
its inputs. Remote execution is reported separately.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_fixtures as fx  # noqa: E402
import lite_schemas  # noqa: E402
import lite_workflow_check  # noqa: E402

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


class WorkflowContractTests(unittest.TestCase):
    def test_all_lite_workflows_pass_the_contract_checks(self):
        report = lite_workflow_check.run()
        self.assertEqual(report["gate"], "PASS", report["failures"])
        self.assertIn(lite_workflow_check.C14_WORKFLOW, report["checked"])
        self.assertIn(lite_workflow_check.C13_WORKFLOW, report["checked"])
        # The POC probe never lived on the default branch: checked when present, never
        # required. Demanding it would fail on the branch this suite protects.
        self.assertEqual(sorted(report["checked"]), sorted(lite_workflow_check.workflow_names()))

    def test_permissions_are_read_only(self):
        for name in lite_workflow_check.workflow_names():
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            self.assertIn("contents: read", text)
            self.assertIn("actions: read", text)
            for forbidden in ("contents: write", "issues: write", "pull-requests: write", "deployments: write", "packages: write"):
                self.assertNotIn(forbidden, text, name)

    def test_no_workflow_can_merge_or_deploy(self):
        for name in lite_workflow_check.workflow_names():
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn("git push", text, name)
            self.assertNotIn("git merge", text, name)
            self.assertNotIn("authorizes_any_action: true", text, name)

    def test_c13_machine_and_ai_jobs_have_different_credentials(self):
        import yaml

        document = yaml.safe_load((WORKFLOW_DIR / lite_workflow_check.C13_WORKFLOW).read_text(encoding="utf-8"))
        machine = json.dumps(document["jobs"]["c13-machine-test"])
        review = json.dumps(document["jobs"]["c13-ai-review"])
        self.assertNotIn("OPENAI_API_KEY", machine)
        self.assertIn("OPENAI_API_KEY", review)
        self.assertIn("docker run", machine)
        self.assertNotIn("docker run", review)
        self.assertIn("postgres:18.4", machine)

    def test_c14_workflow_has_no_quality_sandbox(self):
        text = (WORKFLOW_DIR / lite_workflow_check.C14_WORKFLOW).read_text(encoding="utf-8")
        self.assertNotIn("docker run", text)
        self.assertNotIn("postgres:18.4", text)
        self.assertNotIn("junit", text.lower())

    def test_dispatch_inputs_carry_the_scheduler_binding(self):
        import yaml

        for name in (lite_workflow_check.C14_WORKFLOW, lite_workflow_check.C13_WORKFLOW):
            document = yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))
            triggers = document.get("on") or document.get(True)
            inputs = triggers["workflow_dispatch"]["inputs"]
            for required in ("candidate_sha", "application_tree", "issue_number", "request_id",
                             "ledger_round_id", "c14_task_id", "c13_task_id"):
                self.assertIn(required, inputs, name)
            self.assertLessEqual(len(inputs), 10, name)

    @unittest.skipUnless((WORKFLOW_DIR / lite_workflow_check.POC_WORKFLOW).is_file(),
                         "the POC probe is not part of the default branch")
    def test_poc_workflow_is_isolated_from_real_candidates(self):
        import yaml

        document = yaml.safe_load((WORKFLOW_DIR / lite_workflow_check.POC_WORKFLOW).read_text(encoding="utf-8"))
        self.assertEqual(document["env"]["LITE_CANDIDATE_SHA"], "f" * 40)
        self.assertEqual(document["env"]["LITE_LEDGER_ROUND_ID"], "POC_ONLY")
        text = (WORKFLOW_DIR / lite_workflow_check.POC_WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("POC_ONLY_NO_C13_C14_OPINION", text)


class SchemaTests(unittest.TestCase):
    def test_schema_files_are_up_to_date(self):
        stale = lite_schemas.check(ROOT / "schemas")
        self.assertEqual(stale, [], f"regenerate with lite_schemas.py: {stale}")

    def test_every_schema_is_closed_and_requires_all_fields(self):
        for name, builder in lite_schemas.SCHEMAS.items():
            schema = builder()
            self.assertIs(schema["additionalProperties"], False, name)
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]), name)

    def test_bundle_schemas_keep_authorizes_any_action_false(self):
        for builder in (lite_schemas.c14_bundle_schema, lite_schemas.c13_bundle_schema):
            schema = builder()
            self.assertEqual(schema["properties"]["authorizes_any_action"], {"const": False})

    def test_no_aggregate_root_schema_is_shipped(self):
        """The retired aggregator must not leave a schema behind.

        ``FINAL_ROOT`` and the ``CC_WITNESS`` / ``HK_WITNESS`` slots existed to aggregate
        the two cells into a third root for a witness chain this project deliberately does
        not have. The record is the sealed C14 bundle, the sealed C13 bundle, and GitHub's
        own run identity.
        """
        self.assertNotIn("final_root_v1.schema.json", lite_schemas.SCHEMAS)
        self.assertFalse(hasattr(lite_schemas, "final_root_schema"))

    def test_na_schema_pins_the_not_applicable_verdict(self):
        schema = lite_schemas.c14_na_record_schema()
        self.assertEqual(schema["properties"]["verdict"], {"const": "NOT_APPLICABLE"})
        self.assertEqual(schema["properties"]["not_applicable"]["type"], "object")


class MachineDependencyInstallTests(unittest.TestCase):
    """CCV1-147A: the machine job must install what the candidate declares.

    The defect was proven on a real candidate, not imagined: with pytest alone the inventory
    stopped at ``ModuleNotFoundError: No module named 'cryptography'``, a dependency the
    candidate's own application/pyproject.toml declares. This is the regression guard that
    keeps the fix from being silently reverted.
    """

    TEMPLATE = (
        "name: x\n"
        "jobs:\n"
        "  c13-machine-test:\n"
        "    steps:\n"
        "      - name: Run the frozen machine inventory in a disposable container\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          docker run --rm python:3.12-slim bash -lc '{command}'\n"
    )

    def failures_for(self, command):
        failures = []
        raw = self.TEMPLATE.format(command=command)
        lite_workflow_check.check_machine_step_installs_candidate_dependencies(
            lite_workflow_check.C13_WORKFLOW, {}, raw, failures)
        return failures

    def test_the_shipped_machine_step_installs_the_candidates_own_project(self):
        failures = []
        raw = (WORKFLOW_DIR / lite_workflow_check.C13_WORKFLOW).read_text(encoding="utf-8")
        lite_workflow_check.check_machine_step_installs_candidate_dependencies(
            lite_workflow_check.C13_WORKFLOW, {}, raw, failures)
        self.assertEqual(failures, [])

    def test_installing_only_pytest_is_rejected(self):
        failures = self.failures_for(
            "pip install -q pytest && python -m pytest application/tests -q")
        self.assertTrue(failures, "pytest alone is what broke the first real C13")

    def test_a_dependency_list_written_into_the_workflow_is_rejected(self):
        failures = self.failures_for(
            "pip install -q pytest cryptography && python -m pytest application/tests -q")
        self.assertTrue(failures, "a package list in the workflow is the same defect")

    def test_the_candidate_install_after_pytest_is_rejected(self):
        failures = self.failures_for(
            "pip install -q pytest && python -m pytest application/tests -q"
            " && pip install -q \"/srv/application[dev]\"")
        self.assertTrue(failures, "installing after the run is the same as never")

    def test_another_cell_is_left_alone(self):
        failures = []
        lite_workflow_check.check_machine_step_installs_candidate_dependencies(
            lite_workflow_check.C14_WORKFLOW, {}, "anything", failures)
        self.assertEqual(failures, [])


class MachineDatabaseSelectionTests(unittest.TestCase):
    """The machine container must be given what its own suite reads, not what it advertises,
    and must measure the database it reports.

    Two defects measured on a real round of the frozen inventory:

    * ``application/tests/conftest.py`` picks the database from ``GO_TEST_DATABASE_URL`` and
      overwrites ``DATABASE_URL`` with SQLite when it is absent, so the job published
      ``postgres_version: 18.4`` while every assertion ran on SQLite.
    * ``registration_verification.ready()`` refuses a missing / short / ``dev-`` signing key,
      so four identity tests failed with ``REGISTRATION_VERIFICATION_NOT_READY`` for an
      environmental reason.

    The container is built here from the real workflow's own docker-run shape, so a test
    proves the guard, not the fixture.

    What this guard does NOT do any more is judge the shape of the two values - see
    ``test_value_shape_is_no_longer_the_guards_business``, which asserts the narrowing on
    purpose. Nor does it require the observation to run around the pytest line, which was
    the shape a schema-watching revision needed. The fact those patterns stood in for is now
    measured inside the test process itself, and ``test_lite_database_observation.py``
    executes that measurement.
    """

    TEMPLATE = (
        "name: x\n"
        "jobs:\n"
        "  c13-machine-test:\n"
        "    steps:\n"
        "      - name: Run the frozen machine inventory in a disposable container\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          docker run --rm \\\n"
        "            -v candidate:/srv:ro \\\n"
        "            -v tools/lite_database_observation.py:/opt/lite_database_observation.py:ro \\\n"
        "{arguments}"
        "            -w /srv/application \\\n"
        "            go-c13-machine:local \\\n"
        "            bash -lc '\n"
        "{commands}"
        "            ' c13-tests app\n"
    )

    #: The inventory with the observation plugin loaded, as the shipped step does it.
    OBSERVING = (
        "              python -m pytest -p lite_database_observation application/tests -q --junitxml=/out/junit.xml\n"
    )
    #: The module is MOUNTED and never loaded, so nothing asks the test process which engine
    #: it connected with and the job is back to reporting a version from its own environment.
    UNLOADED = (
        "              python -m pytest application/tests -q --junitxml=/out/junit.xml\n"
    )

    DATABASE_ARGUMENT = (
        '            -e GO_TEST_DATABASE_URL="postgresql+psycopg://postgres:pw@'
        'host.docker.internal:5432/c13_lite" \\\n'
    )
    SIGNING_KEY_ARGUMENT = (
        '            -e JWT_SIGNING_KEY="c13-lite-test-only-signing-key-32bytes" \\\n'
    )

    def failures_for(self, arguments, commands=None):
        if commands is None:
            commands = self.OBSERVING
        failures = []
        raw = self.TEMPLATE.format(arguments=arguments, commands=commands)
        lite_workflow_check.check_machine_step_runs_against_postgres(
            lite_workflow_check.C13_WORKFLOW, {}, raw, failures)
        return failures

    def both(self, database=None, key=None, commands=None):
        if database is None:
            database = self.DATABASE_ARGUMENT
        if key is None:
            key = self.SIGNING_KEY_ARGUMENT
        return self.failures_for(database + key, commands)

    def test_the_shipped_machine_step_runs_against_postgres_with_a_usable_key(self):
        failures = []
        raw = (WORKFLOW_DIR / lite_workflow_check.C13_WORKFLOW).read_text(encoding="utf-8")
        lite_workflow_check.check_machine_step_runs_against_postgres(
            lite_workflow_check.C13_WORKFLOW, {}, raw, failures)
        self.assertEqual(failures, [])

    def test_a_container_without_the_test_database_url_is_rejected(self):
        failures = self.failures_for(self.SIGNING_KEY_ARGUMENT)
        self.assertTrue(
            failures,
            "without GO_TEST_DATABASE_URL the suite runs on SQLite while the manifest "
            "records PostgreSQL")

    def test_a_test_database_url_hidden_behind_a_shell_variable_is_rejected(self):
        indirect = '            -e GO_TEST_DATABASE_URL="$PGURL" \\\n'
        failures = self.both(database=indirect)
        self.assertTrue(failures, "a value the guard cannot read is a value it cannot vouch for")

    def test_a_container_without_a_signing_key_is_rejected(self):
        failures = self.failures_for(self.DATABASE_ARGUMENT)
        self.assertTrue(
            failures,
            "without JWT_SIGNING_KEY registration verification refuses with "
            "REGISTRATION_VERIFICATION_NOT_READY")

    def test_a_step_that_never_loads_the_observation_is_rejected(self):
        """The template MOUNTS the module and never loads it - on purpose.

        Matching the module's name alone was the guard's first shape, and a mutation run
        showed why that was wrong: the real step mounts the module above its pytest line, so
        a step whose observation had been deleted still looked like it had one. What makes
        the plugin observe is pytest importing it, and that is what is checked.
        """
        failures = self.both(commands=self.UNLOADED)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("load the observation plugin", failures[0])

    def test_value_shape_is_no_longer_the_guards_business(self):
        """A SQLite URL or a placeholder key is now caught by the machine that ran.

        Asserted deliberately, so the narrowing is a decision on the record rather than a
        guard someone deleted. Neither value can produce a false GREEN any more: with a
        SQLite URL the engines the suite builds report the ``sqlite`` dialect, the
        observation refuses to name a version, and the manifest carries no version - which
        ``test_lite_database_observation.py`` executes end to end. Re-adding these pattern
        checks would add a second, weaker opinion about something already measured.
        """
        sqlite_argument = '            -e GO_TEST_DATABASE_URL="sqlite+pysqlite:///tmp/x.db" \\\n'
        placeholder = '            -e JWT_SIGNING_KEY="dev-only-change-me-jwt" \\\n'
        self.assertEqual(self.both(database=sqlite_argument, key=placeholder), [])

    def test_the_explanation_alone_does_not_satisfy_the_guard(self):
        # The fixed step explains both defects in prose. A scan that read the explanation as
        # the setting would pass on a step whose real arguments had been deleted.
        prose = (
            "      - name: Run the frozen machine inventory in a disposable container\n"
            "        run: |\n"
            "          # GO_TEST_DATABASE_URL and JWT_SIGNING_KEY are required here.\n"
            "          # -e GO_TEST_DATABASE_URL=\"postgresql+psycopg://x\" \\\n"
            "          # -e JWT_SIGNING_KEY=\"c13-lite-test-only-signing-key-32bytes\" \\\n"
            "          # python -m pytest -p lite_database_observation application/tests \\\n"
            "          docker run --rm -w /srv/application go-c13-machine:local \\\n"
            "            bash -lc 'python -m pytest application/tests -q'\n"
        )
        failures = []
        lite_workflow_check.check_machine_step_runs_against_postgres(
            lite_workflow_check.C13_WORKFLOW, {}, ("name: x\njobs:\n  c13-machine-test:\n"
                                                   "    steps:\n" + prose), failures)
        self.assertEqual(len(failures), 3, failures)

    def test_another_cell_is_left_alone(self):
        failures = []
        lite_workflow_check.check_machine_step_runs_against_postgres(
            lite_workflow_check.C14_WORKFLOW, {}, "anything", failures)
        self.assertEqual(failures, [])


class DispatchEnvRobustnessTests(unittest.TestCase):
    """Regression tests for the two bugs the first real run exposed.

    Both only appear on a runner: $GITHUB_ENV is next-step only, and a push
    triggered run has no ``inputs`` at all, so an "optional" variable arrives empty.
    """

    def run_cli(self, args, env):
        import os
        import subprocess
        import tempfile

        base = {key: value for key, value in os.environ.items()
                if key in ("PATH", "SYSTEMROOT", "HOME", "TEMP", "TMP", "WINDIR", "COMSPEC", "PATHEXT")}
        base.update(env)
        return subprocess.run(
            [sys.executable, str(ROOT / "lite_cli.py")] + args,
            capture_output=True, text=True, env=base, timeout=120,
        )

    def _instant(self, offset_minutes):
        """A dispatch timestamp relative to now.

        Hardcoded instants made this suite expire: once wall-clock passed the frozen
        ``expires_at`` the CLI correctly refused with ``candidate_request_expired``
        and the test failed for a reason unrelated to what it checks.
        """
        import datetime as _datetime

        moment = (_datetime.datetime.now(_datetime.timezone.utc)
                  + _datetime.timedelta(minutes=offset_minutes))
        return moment.isoformat().replace("+00:00", "Z").split(".")[0] + "Z"

    def spec_env(self, directory, scope_sha, rule_input=None):
        env = {
            "LITE_WORKFLOW_IDENTITY": ".github/workflows/c13-c14-lite-poc.yml",
            "LITE_CANDIDATE_SHA": "f" * 40,
            "LITE_APPLICATION_TREE": "f" * 40,
            "LITE_CELL_PAIR": "C13+C14",
            "LITE_REQUEST_ID": "poc-only-request",
            "LITE_LEDGER_ROUND_ID": "POC_ONLY",
            "LITE_C14_TASK_ID": "POC-C14-TASK",
            "LITE_C13_TASK_ID": "POC-C13-TASK",
            "LITE_NONCE": "poc-nonce-000000001",
            "LITE_RUN_ID": "36109708133",
            "LITE_RUN_ATTEMPT": "1",
            "LITE_ISSUED_AT": self._instant(-5),
            "LITE_EXPIRES_AT": self._instant(+55),
            "LITE_WORKFLOW_SHA": "b" * 40,
            "LITE_SCOPE_SHA256": scope_sha,
            "GITHUB_REPOSITORY": "yuguangzhi3836-glitch/GO",
        }
        if rule_input is not None:
            env["LITE_RULE_INPUT"] = str(rule_input)
        return env

    def review_brief(self, directory):
        """The task both cells grade, frozen from the candidate's own pull request.

        ``spec`` requires it for the same reason it requires the diff: the reviewer needs the
        question as well as the answer. Every spec call below stages one, exactly as the
        workflow's read-only review-brief step does.
        """
        return fx.write_review_brief(f"{directory}/review_brief.json", "f" * 40)

    def test_spec_succeeds_when_optional_variables_are_absent(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            rule_input = pathlib.Path(directory, "rule_input.json")
            rule_input.write_text(json.dumps(fx.rule_input_record()), encoding="utf-8")
            changed = pathlib.Path(directory, "changed_paths.txt")
            changed.write_text("application/a.py\n", encoding="utf-8")
            candidate_diff = pathlib.Path(directory, "candidate.diff")
            candidate_diff.write_text(
                "diff --git a/application/a.py b/application/a.py\n", encoding="utf-8")
            scope = self.run_cli(
                ["scope", "--role", "c14", "--rule-input", str(rule_input),
                 "--changed-paths", str(changed), "--out", f"{directory}/scope.json"],
                self.spec_env(directory, "0" * 64, rule_input=rule_input),
            )
            self.assertEqual(scope.returncode, 0, scope.stderr)
            digest = json.loads(pathlib.Path(directory, "scope.json").read_text(encoding="utf-8"))["scope_sha256"]
            self.review_brief(directory)
            spec = self.run_cli(
                ["spec", "--role", "c14", "--scope", f"{directory}/scope.json",
                 "--candidate-diff", str(candidate_diff),
                 "--review-brief", f"{directory}/review_brief.json",
                 "--spec", f"{directory}/spec.json",
                 "--facts", f"{directory}/facts.json", "--contract", f"{directory}/contract.json"],
                self.spec_env(directory, digest, rule_input=rule_input),
            )
            self.assertEqual(spec.returncode, 0, spec.stderr + spec.stdout)
            contract = json.loads(pathlib.Path(directory, "contract.json").read_text(encoding="utf-8"))
            # issue_number was empty, so the ledger reference carries the binding.
            self.assertIsNone(contract["issue_number"])
            self.assertEqual(contract["ledger_reference"]["task_id"], "POC-C14-TASK")

    def test_empty_values_do_not_trip_the_missing_env_check(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            rule_input = pathlib.Path(directory, "rule_input.json")
            rule_input.write_text(json.dumps(fx.rule_input_record()), encoding="utf-8")
            changed = pathlib.Path(directory, "changed_paths.txt")
            changed.write_text("application/a.py\n", encoding="utf-8")
            candidate_diff = pathlib.Path(directory, "candidate.diff")
            candidate_diff.write_text(
                "diff --git a/application/a.py b/application/a.py\n", encoding="utf-8")
            frozen = self.run_cli(
                ["scope", "--role", "c14", "--rule-input", str(rule_input),
                 "--changed-paths", str(changed), "--out", f"{directory}/scope.json"],
                self.spec_env(directory, "0" * 64, rule_input=rule_input),
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            digest = json.loads(
                pathlib.Path(directory, "scope.json").read_text(encoding="utf-8"))["scope_sha256"]
            env = self.spec_env(directory, digest, rule_input=rule_input)
            env.update({"LITE_AI_MODEL": "", "LITE_PRINCIPAL_ID": "", "LITE_ISSUE_NUMBER": ""})
            self.review_brief(directory)
            result = self.run_cli(
                ["spec", "--role", "c14", "--scope", f"{directory}/scope.json",
                 "--candidate-diff", str(candidate_diff),
                 "--review-brief", f"{directory}/review_brief.json",
                 "--spec", f"{directory}/s.json",
                 "--facts", f"{directory}/f.json", "--contract", f"{directory}/c.json"],
                env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("missing dispatch env", result.stderr + result.stdout)

    def test_a_genuinely_missing_required_variable_still_fails(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            env = self.spec_env(directory, "0" * 64)
            del env["LITE_SCOPE_SHA256"]
            self.review_brief(directory)
            result = self.run_cli(
                ["spec", "--role", "c14", "--scope", f"{directory}/scope.json",
                 "--candidate-diff", f"{directory}/candidate.diff",
                 "--review-brief", f"{directory}/review_brief.json",
                 "--spec", f"{directory}/s.json",
                 "--facts", f"{directory}/f.json", "--contract", f"{directory}/c.json"],
                env,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing dispatch env", result.stderr)



class ReviewContentInputGuardTests(unittest.TestCase):
    """CCV1-147B: the reviewer must be given the content, and the guard must see that it is.

    The runtime already fails closed (a missing or empty diff stops the round before any AI
    call), so this aims at the layer below: an edit that drops the arguments or the diff
    generation should be caught when the workflow is reviewed, not by an unexplained red run.
    """

    DIFF_BLOCK = (
        "          git -C candidate diff --no-ext-diff --no-color \"$BASE_SHA\"...HEAD"
        " > \"$RUNNER_TEMP/candidate.diff\"\n"
        "          test -s \"$RUNNER_TEMP/candidate.diff\"\n"
    )

    TEMPLATE = (
        "name: x\n"
        "jobs:\n"
        "  review:\n"
        "    steps:\n"
        "      - name: Freeze the boundary and the diff\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          git -C candidate diff-tree --no-commit-id --name-only -r"
        " --diff-merges=first-parent HEAD | sort -u > \"$RUNNER_TEMP/changed_paths.txt\"\n"
        "          test -s \"$RUNNER_TEMP/changed_paths.txt\"\n"
        "{diff}"
        "      - name: Build the frozen candidate contract\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          python control-plane/c13-c14-lite/lite_cli.py spec --role {role} \\\n"
        "{flags}"
        "            --spec \"$RUNNER_TEMP/x.spec.json\"\n"
    )

    C14_FLAGS = ("            --scope \"$RUNNER_TEMP/scope.json\" \\\n"
                 "            --candidate-diff \"$RUNNER_TEMP/candidate.diff\" \\\n"
                 "            --review-brief \"$RUNNER_TEMP/review_brief.json\" \\\n")
    C13_FLAGS = C14_FLAGS + ("            --machine-manifest \"$RUNNER_TEMP/manifest.json\" \\\n"
                             "            --junit \"$RUNNER_TEMP/junit.xml\" \\\n")

    def failures_for(self, role, flags=None, diff=None):
        raw = self.TEMPLATE.format(
            role=role,
            flags=self.C13_FLAGS if flags is None else flags,
            diff=self.DIFF_BLOCK if diff is None else diff)
        failures = []
        lite_workflow_check.check_spec_carries_the_frozen_review_content(
            lite_workflow_check.C13_WORKFLOW if role == "c13" else lite_workflow_check.C14_WORKFLOW,
            raw, failures)
        return failures

    def test_the_shipped_workflows_pass(self):
        for role, name in (("c14", lite_workflow_check.C14_WORKFLOW),
                           ("c13", lite_workflow_check.C13_WORKFLOW)):
            failures = []
            raw = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            lite_workflow_check.check_spec_carries_the_frozen_review_content(name, raw, failures)
            self.assertEqual(failures, [], name)

    def test_dropping_the_candidate_diff_argument_is_caught(self):
        flags = self.C14_FLAGS.replace(
            "            --candidate-diff \"$RUNNER_TEMP/candidate.diff\" \\\n", "")
        joined = " | ".join(self.failures_for("c14", flags=flags))
        self.assertIn("--candidate-diff", joined)

    def test_dropping_the_scope_argument_is_caught(self):
        flags = self.C14_FLAGS.replace(
            "            --scope \"$RUNNER_TEMP/scope.json\" \\\n", "")
        joined = " | ".join(self.failures_for("c14", flags=flags))
        self.assertIn("--scope", joined)

    def test_dropping_the_machine_evidence_arguments_is_caught_for_c13(self):
        self.assertIn("--machine-manifest",
                      " | ".join(self.failures_for("c13", flags=self.C14_FLAGS)))
        self.assertIn("--junit", " | ".join(self.failures_for("c13", flags=self.C14_FLAGS)))

    def test_removing_the_diff_generation_is_caught(self):
        self.assertTrue(self.failures_for("c14", diff=""), "no diff is ever frozen")

    def test_an_empty_diff_is_not_left_unchecked(self):
        partial = self.DIFF_BLOCK.replace("          test -s \"$RUNNER_TEMP/candidate.diff\"\n", "")
        self.assertTrue(self.failures_for("c14", diff=partial), "an empty diff must be refused")

    def test_the_explanation_alone_does_not_satisfy_the_guard(self):
        """The guard must not be satisfied by the step's own commentary about the defect.

        This is the lesson from the machine-dependency guard: quoting the fixed form inside a
        comment made that guard pass on a file whose real fix had been deleted.
        """
        shipped = (WORKFLOW_DIR / lite_workflow_check.C14_WORKFLOW).read_text(encoding="utf-8")
        rendered = ("\n".join(
            f"          # {line.strip()}"
            if line.strip().startswith("git -C candidate diff ") or
            line.strip().startswith("test -s \"$RUNNER_TEMP/candidate.diff\"")
            else line
            for line in shipped.splitlines()) + "\n")
        self.assertNotEqual(rendered, shipped)
        failures = []
        lite_workflow_check.check_spec_carries_the_frozen_review_content(
            lite_workflow_check.C14_WORKFLOW, rendered, failures)
        self.assertTrue(failures, "a commented-out fix must not satisfy the guard")

    def test_the_poc_probe_is_exempt(self):
        failures = []
        lite_workflow_check.check_spec_carries_the_frozen_review_content(
            lite_workflow_check.POC_WORKFLOW, "name: x\n", failures)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
