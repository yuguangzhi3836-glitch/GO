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

import lite_schemas  # noqa: E402
import lite_workflow_check  # noqa: E402

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


class WorkflowContractTests(unittest.TestCase):
    def test_all_lite_workflows_pass_the_contract_checks(self):
        report = lite_workflow_check.run()
        self.assertEqual(report["gate"], "PASS", report["failures"])
        self.assertIn(lite_workflow_check.C14_WORKFLOW, report["checked"])
        self.assertIn(lite_workflow_check.C13_WORKFLOW, report["checked"])
        self.assertIn(lite_workflow_check.POC_WORKFLOW, report["checked"])

    def test_permissions_are_read_only(self):
        for name in (lite_workflow_check.C14_WORKFLOW, lite_workflow_check.C13_WORKFLOW, lite_workflow_check.POC_WORKFLOW):
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            self.assertIn("contents: read", text)
            self.assertIn("actions: read", text)
            for forbidden in ("contents: write", "issues: write", "pull-requests: write", "deployments: write", "packages: write"):
                self.assertNotIn(forbidden, text, name)

    def test_no_workflow_can_merge_or_deploy(self):
        for name in (lite_workflow_check.C14_WORKFLOW, lite_workflow_check.C13_WORKFLOW, lite_workflow_check.POC_WORKFLOW):
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

    def test_final_root_schema_reserves_the_witness_slots(self):
        schema = lite_schemas.final_root_schema()
        for field in ("CC_WITNESS", "HK_WITNESS"):
            self.assertIn(field, schema["properties"]["body"]["required"])
            self.assertEqual(schema["properties"]["body"]["properties"][field]["type"], ["object", "null"])

    def test_na_schema_pins_the_not_applicable_verdict(self):
        schema = lite_schemas.c14_na_record_schema()
        self.assertEqual(schema["properties"]["verdict"], {"const": "NOT_APPLICABLE"})
        self.assertEqual(schema["properties"]["not_applicable"]["type"], "object")


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

    def spec_env(self, directory, scope_sha):
        return {
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

    def test_spec_succeeds_when_optional_variables_are_absent(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            scope = self.run_cli(
                ["scope", "--role", "c14", "--rule", "POC_ONLY", "--rule-version", "poc",
                 "--out", f"{directory}/scope.json"],
                self.spec_env(directory, "0" * 64),
            )
            self.assertEqual(scope.returncode, 0, scope.stderr)
            digest = json.loads(pathlib.Path(directory, "scope.json").read_text(encoding="utf-8"))["scope_sha256"]
            spec = self.run_cli(
                ["spec", "--role", "c14", "--spec", f"{directory}/spec.json",
                 "--facts", f"{directory}/facts.json", "--contract", f"{directory}/contract.json"],
                self.spec_env(directory, digest),
            )
            self.assertEqual(spec.returncode, 0, spec.stderr + spec.stdout)
            contract = json.loads(pathlib.Path(directory, "contract.json").read_text(encoding="utf-8"))
            # issue_number was empty, so the ledger reference carries the binding.
            self.assertIsNone(contract["issue_number"])
            self.assertEqual(contract["ledger_reference"]["task_id"], "POC-C14-TASK")

    def test_empty_values_do_not_trip_the_missing_env_check(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            env = self.spec_env(directory, "0" * 64)
            env.update({"LITE_AI_MODEL": "", "LITE_PRINCIPAL_ID": "", "LITE_ISSUE_NUMBER": ""})
            result = self.run_cli(
                ["spec", "--role", "c14", "--spec", f"{directory}/s.json",
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
            result = self.run_cli(
                ["spec", "--role", "c14", "--spec", f"{directory}/s.json",
                 "--facts", f"{directory}/f.json", "--contract", f"{directory}/c.json"],
                env,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing dispatch env", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
