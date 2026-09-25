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


if __name__ == "__main__":
    unittest.main(verbosity=2)
