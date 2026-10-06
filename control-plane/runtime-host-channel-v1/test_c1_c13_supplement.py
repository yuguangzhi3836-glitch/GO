"""Offline admission tests with real SQLite outbox persistence, no paid dispatch."""
import copy
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

    def tearDown(self):
        self.outbox.close()
        self.tmp.cleanup()

    def plan(self):
        return ingress.plan_from_outbox(self.parsed,self.outbox,enabled=True)

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
        self.outbox._db.execute("UPDATE c1_dispatch SET result_sha256='wrong'")
        with self.assertRaisesRegex(contract.Refused,"DIGEST_MISMATCH"):
            self.plan()
        self.outbox._db.execute("DELETE FROM c1_dispatch")
        with self.assertRaisesRegex(contract.Refused,"RESULT_MISSING"):
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

    def test_existing_issue_ingest_repeated_and_after_restart_is_one_enqueue_identity(self):
        issue=dict(number=fixed.ISSUE,state="open",title="C14 · REVIEW · same issue",
                   body=f"Candidate PR: #{fixed.PR}\nCandidate SHA: {fixed.CANDIDATE}\nC13 supplement: {fixed.PROFILE}")
        class Reader:
            def read_pull(self,n): return dict(head_sha=fixed.CANDIDATE,base_ref="main")
            def read_commit_tree(self,s): return "a"*40
            def read_tree(self,s): return [dict(path="application",type="tree",sha=fixed.APPLICATION_TREE)]
        class Runtime:
            def __init__(self): self.tasks={}
            def enqueue(self,owner,kind,payload,*,idempotency_key,max_attempts):
                record=(owner,kind,payload,max_attempts)
                if idempotency_key in self.tasks:
                    assert self.tasks[idempotency_key]==record
                self.tasks[idempotency_key]=copy.deepcopy(record)
                return "one-correction-task"
        runtime=Runtime()
        with patch.object(ingress,"installed_plan",side_effect=lambda p,enabled: ingress.plan_from_outbox(p,self.outbox,enabled=enabled)):
            for _ in range(3):
                result=review_ingress.ingest_review(issue,reader=Reader(),runtime=runtime,
                                                   environ={INGRESS_ENABLED_ENV:"true"})
                self.assertEqual(result["runtime_task_id"],"one-correction-task")
                self.outbox.close()
                self.outbox=DispatchOutbox(str(self.db))
        self.assertEqual(len(runtime.tasks),1)
        self.assertEqual(next(iter(runtime.tasks.values()))[:2],("C13",contract.C13_REVIEW_KIND))

    def test_duplicate_or_unknown_profile_not_allowed(self):
        for body in ("C13 supplement: other",f"C13 supplement: {fixed.PROFILE}\nC13 supplement: {fixed.PROFILE}"):
            with self.assertRaises(ValueError): fixed.requested_profile(body)
        self.assertIsNone(fixed.requested_profile("ordinary comment prose"))


if __name__ == "__main__": unittest.main()
