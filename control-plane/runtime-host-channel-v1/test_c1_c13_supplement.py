"""Offline admission tests with real SQLite outbox persistence, no paid dispatch."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import c1_c13_supplement_contract as fixed
import c1_c13_supplement_ingress as ingress
import c1_execution_contract as contract
from c1_dispatch_outbox import DispatchOutbox
from c1_issue_ingress import INGRESS_ENABLED_ENV
import c1_review_issue_ingress as review_ingress

# The post-#540 machine-inventory parser lives in the C13 suite. It is loaded by path rather
# than by inserting that directory into sys.path, so this module cannot change what any other
# test module in this suite is able to import.
_LITE_DIR = Path(__file__).resolve().parents[1] / "c13-c14-lite"
_spec = importlib.util.spec_from_file_location(
    "_lite_machine_inventory_under_test", _LITE_DIR / "lite_machine_inventory.py")
lite_machine_inventory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lite_machine_inventory)

# Issue #533 as it is LIVE on 2026-10-07: title and body, verbatim. The body still ends with
# the consumed V1 marker, and the real bytes are kept here so that this regression cannot
# drift into testing a paraphrase of the one line that would actually have fired the slot.
ISSUE_533_TITLE = "C14 · REVIEW · #531 当前SHA支付UNKNOWN恢复与PG18.4修复复审"
ISSUE_533_BODY = """\
Candidate PR: #531
Candidate SHA: 0b7d0403f9f171844fdcf9bf3330ff9386e82943
Base main: 00dcf6007fee0513b9ef6184209782d67cad7c0c

目标：对 #531 当前冻结SHA做一次新的正式 C14→C13 独立复审。旧 #532 的 FAIL/C14-CC-001 永久保留，不原样重跑，不把旧FAIL改写成PASS。

已知新证据：
- 本地冻结范围 24 PASS，0 failure/error/skip；SQLite，仅作本地回归证据。
- 当前SHA对应 UNKNOWN recovery PostgreSQL verification run 37479164391 已 completed/success；必须读回其原始 job logs / artifact / JUnit / database.json，确认 PostgreSQL 18.4、candidate SHA、migration exit、pytest counts 与源码绑定后，才可计为PG证据。
- Registration candidate acceptance run 37479164408 completed/success。
- 修复包括 reservation_state 40→64、omnichannel ledger account_code 64→128，以及0137迁移的历史保留/拒绝有损downgrade。
- UNKNOWN恢复仍限定隔离/test/demo；不得推导为真实PSP、真实provider reconciliation或生产可用。

C14重点：
1. 复核 PRODUCT_FEATURE + PRODUCT_FIX + MIGRATION + BUILD + TEST_ONLY + DOCUMENTATION 分类及权限边界整改是否关闭旧 C14-CC-001。
2. 复核HTTP恢复入口：live finance user/session + reserved same-hotel operations grant；普通staff不能铸造reserved role；撤销/跨酒店/admin-only均拒绝；事务内重查。
3. 复核 source/stay/authorization→movement→episode 锁序、旧generation拒绝、lost-response replay不二次扣款/不重开UNKNOWN、audit失败全回滚。
4. 复核0136→0137迁移链、字段扩宽、索引/历史值保留和downgrade防截断。
5. 读取 run37479164391 原始证据，不能仅凭Actions绿色判PASS。

C13在且仅在C14 PASS后：
- 实际执行冻结5路径：
  tests/test_v70_r4_c01_unknown_episode.py
  tests/test_unknown_episode_retention.py
  tests/test_v70_next_c01_unknown_funding.py
  tests/test_depth06_direct_checkout.py::test_unknown_funds_keep_inventory_and_block_cancel_and_timeout
  tests/test_depth25_migration_history.py
- 核对当前SHA、本地24项与PG定向15项的证据边界。
- 不得把这些结果冒充原18组完整支付验收。

范围限制：
不合并、不部署、不接真实PSP、不动HK/rt01、不访问真实资金/供应商/SMTP；高并发ABBA继续暂停。本轮只收口当前支付候选的独立审核。若审核额度/权限失败，标BLOCKED，不加预算、不原样重跑。

C13 supplement: PG533-15-V1
"""

# The one explicit activation: the same issue and the same frozen candidate, with the marker
# switched by hand. Nothing else differs, which is what makes it an activation and not a plan.
ACTIVATION_BODY = (f"Candidate PR: #{fixed.PR}\n"
                   f"Candidate SHA: {fixed.CANDIDATE}\n"
                   f"C13 supplement: {fixed.ACTIVATION_PROFILE}\n")


class Reader:
    """The four GET-only reads the review ingress makes, at the frozen candidate."""

    def read_pull(self, number):
        return dict(head_sha=fixed.CANDIDATE, base_ref="main")

    def read_commit_tree(self, sha):
        return "a" * 40

    def read_tree(self, sha):
        return [dict(path="application", type="tree", sha=fixed.APPLICATION_TREE)]

    def read_pull_files(self, number):
        return []


class RecordingRuntime:
    """A Runtime that records what it was asked to create instead of creating it."""

    def __init__(self):
        self.calls = []

    def enqueue(self, owner, kind, payload, *, idempotency_key, max_attempts):
        self.calls.append(dict(owner_c=owner, kind=kind, idempotency_key=idempotency_key,
                               max_attempts=max_attempts, payload=copy.deepcopy(payload)))
        return "one-correction-task"


class SupplementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "outbox.db"
        self.outbox = DispatchOutbox(str(self.db))
        self.parsed = dict(issue_number=fixed.ISSUE, candidate_pr_number=fixed.PR,
                           candidate_sha=fixed.CANDIDATE)
        self.payload = dict(schema_version=1, cell_id="C13", external_task_id=fixed.C13_TASK,
            candidate_sha=fixed.CANDIDATE, application_tree=fixed.APPLICATION_TREE,
            issue_number=fixed.ISSUE, review_request_id="original-request",
            ledger_round_id=fixed.ROUND, c14_task_id=fixed.C14_TASK, c13_task_id=fixed.C13_TASK,
            c14_run_id=fixed.C14_RUN, c14_runtime_task_id=fixed.C14_RUNTIME,
            machine_inventory="application/tests/test_unknown_episode_retention.py")
        self.documents = {}
        for cell, runtime_id, kind, run, root, verdict in (
            ("C13",fixed.C13_RUNTIME,contract.C13_REVIEW_KIND,fixed.C13_RUN,fixed.C13_ROOT,"BLOCKED"),
            ("C14",fixed.C14_RUNTIME,contract.C14_REVIEW_KIND,fixed.C14_RUN,fixed.C14_ROOT,"PASS_SCOPED"),
        ):
            request_id = contract.sha256_hex("synthetic request " + cell)
            doc = dict(version=1,kind=contract.REVIEW_RESULT_KIND,owner_c=cell,runtime_task_id=runtime_id,
                attempt=1,execution_request_id=request_id,github_run_id=run,github_run_attempt=1,
                provider=contract.PROVIDER_GHAW_BUILDER,review_verdict=verdict,deployment_eligible=False,
                accepted=True,authorizes_any_action=False,candidate_sha=fixed.CANDIDATE,
                application_tree=fixed.APPLICATION_TREE,issue_number=fixed.ISSUE,
                review_request_id="original-request",ledger_round_id=fixed.ROUND,
                sealed_bundle_root=root,sealed_bundle_sha256="a"*64,artifacts={"c13_bundle.json":"a"*64},
                status="SUCCEEDED",round_decision=None if cell=="C14" else {"decision":"BLOCK","authorizes_any_action":False})
            request = dict(task_kind=kind,payload=self.payload,execution_request_id=request_id)
            # Synthetic transport fixture inserted at its exact original identity.
            self.outbox._db.execute("INSERT INTO c1_dispatch (execution_request_id,runtime_task_id,attempt,state,result_json,result_sha256,request_json,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (request_id,runtime_id,1,"COMPLETED",contract.canonical(doc),
                 contract.sha256_hex(contract.canonical(doc)),contract.canonical(request),"synthetic"))
            self.documents[cell] = doc
        failed_payload = copy.deepcopy(self.payload)
        failed_payload.update(machine_inventory=fixed.INVENTORY,
                              supplement=copy.deepcopy(fixed.ENVELOPE))
        failed_request = dict(runtime_task_id=fixed.FAILED_CORRECTION_RUNTIME, attempt=1,
            execution_request_id=fixed.FAILED_CORRECTION_REQUEST, owner_c="C13",
            task_kind=contract.C13_REVIEW_KIND, payload=failed_payload)
        self.outbox._db.execute(
            "INSERT INTO c1_dispatch (execution_request_id,runtime_task_id,attempt,state,"
            "dispatches_sent,github_run_id,failure_reason,request_json,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (fixed.FAILED_CORRECTION_REQUEST, fixed.FAILED_CORRECTION_RUNTIME, 1,
             "RUN_FAILED", 1, fixed.FAILED_CORRECTION_RUN, "EXECUTION_RUN_FAILED",
             contract.canonical(failed_request), "synthetic"))

    def tearDown(self):
        self.outbox.close()
        self.tmp.cleanup()

    def plan(self):
        return ingress.plan_from_outbox(self.parsed,self.outbox,enabled=True)

    def supplement_installed(self):
        """Point `installed_plan` at this test's private outbox instead of /var/lib."""
        return patch.object(ingress,"installed_plan",
            side_effect=lambda parsed,enabled: ingress.plan_from_outbox(
                parsed,self.outbox,enabled=enabled))

    def ingest(self, body, runtime, *, title=ISSUE_533_TITLE):
        issue = dict(number=fixed.ISSUE,state="open",title=title,body=body)
        return review_ingress.ingest_review(issue,reader=Reader(),runtime=runtime,
                                            environ={INGRESS_ENABLED_ENV:"true"})

    def plan_only(self, body, *, title=ISSUE_533_TITLE):
        issue = dict(number=fixed.ISSUE,state="open",title=title,body=body)
        return review_ingress.plan_review_ingress(issue,reader=Reader(),
                                                  environ={INGRESS_ENABLED_ENV:"true"})

    # ---------------------------------------------------------------- the slot itself
    def test_one_scoped_payload_preserves_review_identity_model_and_limits(self):
        plan = self.plan()
        call = plan["would_enqueue"]
        self.assertEqual(call["kind"],contract.C13_REVIEW_KIND)
        self.assertEqual(call["max_attempts"],1)
        self.assertEqual(call["payload"]["review_request_id"],"original-request")
        self.assertNotIn("ai_model",call["payload"])
        self.assertEqual(call["payload"]["machine_inventory"],fixed.INVENTORY)
        self.assertEqual(call["idempotency_key"],fixed.IDEMPOTENCY_KEY)
        self.assertFalse(plan["enqueued"])
        self.assertEqual(self.plan(),plan)

    def test_read_only_reopen_does_not_create_database_and_cannot_write(self):
        ro = DispatchOutbox(str(self.db),read_only=True)
        try:
            self.assertEqual(ingress.plan_from_outbox(self.parsed,ro,enabled=True),self.plan())
            with self.assertRaises(Exception):
                ro._db.execute("DELETE FROM c1_dispatch")
        finally:
            ro.close()
        missing=Path(self.tmp.name)/"absent.db"
        with self.assertRaises(Exception):
            DispatchOutbox(str(missing),read_only=True)
        self.assertFalse(missing.exists())

    def test_mutated_issue_or_candidate_refuses(self):
        for field in self.parsed:
            with self.subTest(field=field), self.assertRaises(contract.Refused):
                ingress.plan_from_outbox(dict(self.parsed,**{field:"wrong"}),self.outbox,enabled=True)

    def test_missing_predecessor_and_tampered_result_refuse(self):
        self.outbox._db.execute(
            "UPDATE c1_dispatch SET result_sha256='wrong' WHERE result_json IS NOT NULL")
        with self.assertRaisesRegex(contract.Refused,"DIGEST_MISMATCH"):
            self.plan()
        self.outbox._db.execute("DELETE FROM c1_dispatch")
        with self.assertRaisesRegex(contract.Refused,"RESULT_MISSING"):
            self.plan()

    def test_final_slot_requires_the_exact_failed_correction(self):
        mutations = (
            ("state", "RUN_BOUND"), ("dispatches_sent", 0),
            ("github_run_id", fixed.FAILED_CORRECTION_RUN + 1),
            ("failure_reason", None),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                self.outbox._db.execute(
                    f"UPDATE c1_dispatch SET {field}=? WHERE execution_request_id=?",
                    (value, fixed.FAILED_CORRECTION_REQUEST))
                with self.assertRaisesRegex(contract.Refused, "PRIOR_CORRECTION_MISMATCH"):
                    self.plan()
                self.outbox.close()
                self.outbox = DispatchOutbox(str(self.db))
                reset = {"state": "RUN_FAILED", "dispatches_sent": 1,
                         "github_run_id": fixed.FAILED_CORRECTION_RUN,
                         "failure_reason": "EXECUTION_RUN_FAILED"}
                self.outbox._db.execute(
                    f"UPDATE c1_dispatch SET {field}=? WHERE execution_request_id=?",
                    (reset[field], fixed.FAILED_CORRECTION_REQUEST))
        self.outbox._db.execute(
            "DELETE FROM c1_dispatch WHERE execution_request_id=?",
            (fixed.FAILED_CORRECTION_REQUEST,))
        with self.assertRaisesRegex(contract.Refused, "PRIOR_CORRECTION_MISSING"):
            self.plan()

    def test_wire_envelope_survives_contract_and_cannot_expand_scope(self):
        payload=self.plan()["would_enqueue"]["payload"]
        request=dict(runtime_task_id="new-runtime-task",attempt=1,execution_request_id="a"*64,
                     owner_c="C13",task_kind=contract.C13_REVIEW_KIND,payload=payload)
        wire=contract.dispatch_inputs(request)
        self.assertEqual(json.loads(wire["runtime_transport"])["supplement"],fixed.ENVELOPE)
        self.assertLessEqual(len(wire),10)
        for field,value in (("machine_inventory","application/tests"),("candidate_sha","b"*40),
                             ("cell_id","C14"),("issue_number",534)):
            with self.subTest(field=field),self.assertRaises(contract.Refused):
                contract.validate_review_task_payload(dict(payload,**{field:value}),allowed_owner_cs=("C13","C14"))

    # ------------------------------------------------- who may open the recovery slot
    def test_the_live_533_body_with_the_consumed_v1_marker_is_inert(self):
        """A: the marker that is on #533 right now must not be able to open the slot."""
        # The fixture really is the live issue, and it really does still carry V1.
        self.assertEqual(ISSUE_533_TITLE.split(" · ", 2)[0], "C14")
        self.assertEqual(ISSUE_533_TITLE.split(" · ", 2)[1], "REVIEW")
        self.assertTrue(ISSUE_533_BODY.rstrip().endswith("C13 supplement: " + fixed.PROFILE))
        self.assertEqual(fixed.requested_profile.__module__, fixed.__name__)
        # The parser names the consumed generation. It must NOT answer "no supplement":
        # returning None would hand the issue to the ordinary review path and commission a
        # second C14 for a scope that already has one.
        with self.assertRaisesRegex(ValueError, "^C13_SUPPLEMENT_V1_CONSUMED$"):
            fixed.requested_profile(ISSUE_533_BODY)
        # The real ingest entry point refuses, and refuses BEFORE any Runtime call.
        runtime = RecordingRuntime()
        with self.supplement_installed(), self.assertRaisesRegex(
                contract.Refused, "^C13_SUPPLEMENT_V1_CONSUMED$"):
            self.ingest(ISSUE_533_BODY, runtime)
        self.assertEqual(runtime.calls, [], "the consumed marker must not create any task")
        # A refusal that still produced a plan would be a plan: prove none exists.
        with self.assertRaisesRegex(contract.Refused, "^C13_SUPPLEMENT_V1_CONSUMED$"):
            self.plan_only(ISSUE_533_BODY)

    def test_the_activation_profile_is_the_only_explicit_trigger(self):
        """B: switching the marker by hand is the one explicit activation."""
        self.assertEqual(fixed.requested_profile(ACTIVATION_BODY), fixed.ACTIVATION_PROFILE)
        runtime = RecordingRuntime()
        with self.supplement_installed():
            result = self.ingest(ACTIVATION_BODY, runtime)
        self.assertEqual(result["action"], "ENQUEUED")
        self.assertTrue(result["enqueued"])
        self.assertEqual(result["runtime_task_id"], "one-correction-task")
        self.assertEqual(len(runtime.calls), 1)
        call = runtime.calls[0]
        self.assertEqual((call["owner_c"], call["kind"]), ("C13", contract.C13_REVIEW_KIND))
        self.assertEqual(call["max_attempts"], 1)
        self.assertEqual(call["idempotency_key"], fixed.IDEMPOTENCY_KEY)
        self.assertEqual(call["idempotency_key"], "c13-pg-correction-v2:" + fixed.ROUND)
        self.assertNotEqual(call["idempotency_key"], "c13-pg-correction-v1:" + fixed.ROUND)
        self.assertEqual(call["payload"]["machine_inventory"], fixed.INVENTORY)
        self.assertEqual(call["payload"]["candidate_sha"], fixed.CANDIDATE)
        self.assertEqual(call["payload"]["issue_number"], fixed.ISSUE)
        self.assertEqual(call["payload"]["supplement"], fixed.ENVELOPE)

    def test_activation_profile_ingest_repeated_and_after_restart_is_one_enqueue_identity(self):
        """C: re-polling V2 is free; the kernel answers with the task it already has."""
        issue = dict(number=fixed.ISSUE,state="open",title=ISSUE_533_TITLE,body=ACTIVATION_BODY)

        class Runtime:
            def __init__(self):
                self.tasks = {}

            def enqueue(self, owner, kind, payload, *, idempotency_key, max_attempts):
                record = (owner, kind, payload, max_attempts)
                if idempotency_key in self.tasks:
                    assert self.tasks[idempotency_key] == record
                self.tasks[idempotency_key] = copy.deepcopy(record)
                return "one-correction-task"

        runtime = Runtime()
        with self.supplement_installed():
            for _ in range(3):
                result = review_ingress.ingest_review(
                    issue, reader=Reader(), runtime=runtime,
                    environ={INGRESS_ENABLED_ENV:"true"})
                self.assertEqual(result["runtime_task_id"], "one-correction-task")
                self.outbox.close()
                self.outbox = DispatchOutbox(str(self.db))
        self.assertEqual(len(runtime.tasks), 1)
        self.assertEqual(list(runtime.tasks), [fixed.IDEMPOTENCY_KEY])
        self.assertEqual(next(iter(runtime.tasks.values()))[:2], ("C13", contract.C13_REVIEW_KIND))

    def test_a_body_carrying_both_markers_is_refused(self):
        """D: a half-finished V1 -> V2 edit must not half-activate the slot."""
        body = (f"Candidate PR: #{fixed.PR}\nCandidate SHA: {fixed.CANDIDATE}\n"
                f"C13 supplement: {fixed.ACTIVATION_PROFILE}\n"
                f"C13 supplement: {fixed.PROFILE}\n")
        with self.assertRaisesRegex(ValueError, "^C13_SUPPLEMENT_V1_CONSUMED$"):
            fixed.requested_profile(body)
        runtime = RecordingRuntime()
        with self.supplement_installed(), self.assertRaisesRegex(
                contract.Refused, "^C13_SUPPLEMENT_V1_CONSUMED$"):
            self.ingest(body, runtime)
        self.assertEqual(runtime.calls, [])

    def test_an_unknown_or_v1_derived_marker_cannot_activate(self):
        """E: anything that is not exactly the activation profile fails closed."""
        for value in ("PG533-15-V3", "PG533-15-V10", "pg533-15-v2",
                      "PG533-15-V2-", "c13-pg-correction-v2:" + fixed.ROUND, ""):
            with self.subTest(value=value):
                body = (f"Candidate PR: #{fixed.PR}\nCandidate SHA: {fixed.CANDIDATE}\n"
                        f"C13 supplement: {value}\n")
                with self.assertRaisesRegex(ValueError, "^C13_SUPPLEMENT_PROFILE_NOT_AUTHORIZED$"):
                    fixed.requested_profile(body)
                runtime = RecordingRuntime()
                with self.supplement_installed(), self.assertRaises(contract.Refused):
                    self.ingest(body, runtime)
                self.assertEqual(runtime.calls, [], value)
        # Surrounding whitespace is trimmed to the same identity, exactly as before this
        # guard: activation is case- and token-exact, not whitespace-exact.
        for value in ("PG533-15-V2 ", " PG533-15-V2", "PG533-15-V2\t"):
            with self.subTest(value=value):
                self.assertEqual(
                    fixed.requested_profile("C13 supplement: " + value),
                    fixed.ACTIVATION_PROFILE)
        # ...and the marker's own spelling is matched case-insensitively, as before.
        self.assertEqual(fixed.requested_profile("C13 SUPPLEMENT: PG533-15-V2"),
                         fixed.ACTIVATION_PROFILE)

    def test_a_body_without_the_marker_never_enters_the_supplement(self):
        """F: an ordinary review issue keeps the ordinary path, and only that path."""
        body = f"Candidate PR: #{fixed.PR}\nCandidate SHA: {fixed.CANDIDATE}\n"
        self.assertIsNone(fixed.requested_profile(body))
        with patch.object(ingress,"installed_plan",
                          side_effect=AssertionError("the supplement path must not run")):
            plan = self.plan_only(body)
        self.assertEqual((plan["would_enqueue"]["owner_c"], plan["would_enqueue"]["kind"]),
                         ("C14", contract.C14_REVIEW_KIND))
        self.assertEqual(plan["would_enqueue"]["max_attempts"], 1)
        self.assertNotEqual(plan["would_enqueue"]["idempotency_key"], fixed.IDEMPOTENCY_KEY)
        self.assertNotEqual(plan["would_enqueue"]["idempotency_key"],
                            "c13-pg-correction-v2:" + fixed.ROUND)
        self.assertEqual(plan["action"], "SHADOW_PLAN")

    def test_the_activated_plan_carries_the_exact_pg533_node_inventory(self):
        """G: the activated slot still passes the frozen node id through the #540 parser."""
        with self.supplement_installed():
            plan = self.ingest(ACTIVATION_BODY, RecordingRuntime())
        inventory = plan["would_enqueue"]["payload"]["machine_inventory"]
        self.assertEqual(inventory, fixed.INVENTORY)
        self.assertIn("::", inventory)
        root = Path(self.tmp.name) / "candidate"
        (root / "application/tests").mkdir(parents=True)
        for token in fixed.BUSINESS_PATHS:
            (root / token.split("::", 1)[0]).write_text("")
        # Four files and one node id: the node id stays ONE literal argv element.
        self.assertEqual(lite_machine_inventory.inventory_paths(inventory, root),
                         ["/srv/" + token for token in fixed.BUSINESS_PATHS])
        # The selector is never resolved as a filesystem path - pytest owns collection.
        self.assertEqual(
            lite_machine_inventory.inventory_paths(
                "application/tests/test_depth06_direct_checkout.py::test_not_written_yet", root),
            ["/srv/application/tests/test_depth06_direct_checkout.py::test_not_written_yet"])
        # ...while a candidate-controlled command fragment is still refused.
        for bad in (inventory + ";touch /tmp/evil",
                    "application/tests/test_depth06_direct_checkout.py::test_x;id"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "INVALID_TEST_PATH"):
                lite_machine_inventory.inventory_paths(bad, root)

    def test_consumed_duplicate_and_unknown_markers_are_all_refused(self):
        cases = {
            f"C13 supplement: {fixed.PROFILE}": "C13_SUPPLEMENT_V1_CONSUMED",
            f"C13 supplement: {fixed.PROFILE}\nC13 supplement: {fixed.PROFILE}": "C13_SUPPLEMENT_V1_CONSUMED",
            f"C13 supplement: {fixed.ACTIVATION_PROFILE}\nC13 supplement: {fixed.ACTIVATION_PROFILE}": "C13_SUPPLEMENT_PROFILE_NOT_AUTHORIZED",
            "C13 supplement: other": "C13_SUPPLEMENT_PROFILE_NOT_AUTHORIZED",
            "C13 supplement:": "C13_SUPPLEMENT_PROFILE_NOT_AUTHORIZED",
        }
        for body, reason in cases.items():
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, reason):
                fixed.requested_profile(body)
        self.assertIsNone(fixed.requested_profile("ordinary comment prose"))
        self.assertIsNone(fixed.requested_profile(""))
        self.assertEqual(fixed.ACTIVATION_PROFILE, "PG533-15-V2")
        self.assertEqual(fixed.PROFILE, "PG533-15-V1")
        self.assertNotEqual(fixed.PROFILE, fixed.ACTIVATION_PROFILE)


if __name__ == "__main__": unittest.main()
