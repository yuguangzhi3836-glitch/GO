"""Synthetic machine-part aggregation and backend refusal tests; no PostgreSQL claim."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import lite_bundle
import lite_fixtures
import lite_pg533 as backend
from lite_pg533 import fixed


def raw(doc): return json.dumps(doc,sort_keys=True).encode()


def junit(ids):
    suite=ET.Element("testsuite",tests=str(len(ids)),failures="0",errors="0",skipped="0")
    for node in ids:
        path,name=node.split("::",1)
        ET.SubElement(suite,"testcase",classname=path[:-3].replace("/","."),name=name)
    return ET.tostring(suite)


class PG533Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.prior,self.review,self.c14dir,self.fresh=[self.root/n for n in ("prior","review","c14","fresh")]
        for p in (self.prior,self.review,self.c14dir,self.fresh): p.mkdir()
        self.ids=[]
        for path,count in fixed.CASE_COUNTS.items():
            self.ids.extend([path if "::" in path else path+"::test_new_"+str(i) for i in range(count)])
        oldids=["tests/test_depth25_migration_history.py::test_old_"+str(i) for i in range(9)]
        oldids += ["tests/test_unknown_episode_retention.py::test_old_"+str(i) for i in range(7)]
        oldids += ["tests/test_v70_r4_c01_unknown_episode.py::test_old_"+str(i) for i in range(4)]
        oldfiles={"junit.xml":junit(oldids),"stdout.txt":b"synthetic original20",
                  "test_inventory.txt":b"synthetic old inventory\n","manifest.json":b'{"synthetic":true}'}
        for name,value in oldfiles.items(): (self.prior/name).write_bytes(value)
        round_=lite_fixtures.make_round(candidate_sha=fixed.CANDIDATE,application_tree=fixed.APPLICATION_TREE,
                                        c13_verdict="BLOCKED",c13_run_id=fixed.C13_RUN,c14_run_id=fixed.C14_RUN)
        c14=round_["c14_bundle"]
        c14["issue_number"]=fixed.ISSUE
        c14=lite_bundle.seal(c14)
        c13=round_["c13_bundle"]
        c13["issue_number"]=fixed.ISSUE
        c13["c14_prerequisite"]["c14_root"]=c14["C14_ROOT"]
        for name,key in (("junit.xml","junit_sha256"),("stdout.txt","stdout_sha256"),
                         ("manifest.json","manifest_sha256"),("test_inventory.txt","test_inventory_sha256")):
            c13["machine_job"][key]=backend.sha(oldfiles[name])
            if key in c13:c13[key]=backend.sha(oldfiles[name])
        c13=lite_bundle.seal(c13)
        (self.review/"c13_bundle.json").write_bytes(raw(c13))
        (self.c14dir/"c14_bundle.json").write_bytes(raw(c14))
        self.patches=[patch.object(fixed,"C13_ROOT",c13["C13_ROOT"]),patch.object(fixed,"C14_ROOT",c14["C14_ROOT"])]
        for p in self.patches:p.start()
        self.observation=dict(dialect="postgresql",server_version_num=180004,database="c13_lite")
        self.database=dict(candidate_sha=fixed.CANDIDATE,application_tree=fixed.APPLICATION_TREE,
            profile=fixed.PROFILE,pytest_exit_code=0,observed_cases={node:{"before":dict(self.observation),
                "after":dict(self.observation)} for node in self.ids})
        (self.fresh/"junit.xml").write_bytes(junit(self.ids))
        (self.fresh/"stdout.txt").write_bytes(b"synthetic fresh15")
        (self.fresh/"test_inventory.txt").write_text(fixed.INVENTORY+"\n")
        self.write_manifest()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def write_manifest(self):
        (self.fresh/"database.json").write_bytes(raw(self.database))
        self.manifest=dict(candidate_sha=fixed.CANDIDATE,application_tree=fixed.APPLICATION_TREE,
            inventory=fixed.INVENTORY,exit_code=0,step_outcome="success",docker_used=True,
            postgres_version="18.4")
        for name,key in (("junit.xml","junit_sha256"),("stdout.txt","stdout_sha256"),("database.json","database_sha256")):
            self.manifest[key]=backend.sha((self.fresh/name).read_bytes())
        (self.fresh/"manifest.json").write_bytes(raw(self.manifest))

    def assemble(self,**over):
        return backend.assemble(self.prior,self.review,self.c14dir,self.fresh,
                                **dict(run_id=999999,run_attempt=1,**over))

    def test_full_assembly_retains_nine_sqlite_and_fifteen_pg_with_original_parts(self):
        result=self.assemble()
        joined=backend.cases((self.fresh/"junit.xml").read_bytes())
        self.assertEqual(len(joined),24)
        self.assertEqual(sum(c.get("name").startswith("test_old_") for c in joined),9)
        self.assertEqual(result["evidence_parts"][0]["dialect"],"sqlite")
        self.assertEqual(result["evidence_parts"][1]["fresh_cases"],15)
        self.assertFalse(result["authorizes_any_action"])
        self.assertEqual((self.fresh/"parts/prior-stdout.txt").read_bytes(),b"synthetic original20")
        self.assertEqual(result["junit_sha256"],backend.sha((self.fresh/"junit.xml").read_bytes()))
        self.assertEqual(result["database_observation"],self.database)

    def test_prior_tampering_refuses_before_aggregation(self):
        (self.prior/"stdout.txt").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError,"PRIOR_DIGEST"):self.assemble()
        self.assertFalse((self.fresh/"parts").exists())

    def test_false_version_label_does_not_replace_per_case_engine_proof(self):
        self.database["observed_cases"][self.ids[0]]["after"]["dialect"]="sqlite"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,"CASE_NOT_OBSERVED"):self.assemble()

    def test_missing_engine_observation_refuses(self):
        del self.database["observed_cases"][self.ids[0]]
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,"MISSING_PER_CASE"):self.assemble()

    def test_missing_case_refuses_even_if_manifest_hashes_are_updated(self):
        (self.fresh/"junit.xml").write_bytes(junit(self.ids[:-1]))
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,"EXACTLY_15"):self.assemble()

    def test_skipped_or_failed_case_refuses(self):
        root=ET.fromstring((self.fresh/"junit.xml").read_bytes())
        ET.SubElement(root[0],"skipped")
        (self.fresh/"junit.xml").write_bytes(ET.tostring(root))
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,"NONPASS"):self.assemble()

    def test_wrong_candidate_or_digest_refuses(self):
        self.database["candidate_sha"]="e"*40
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,"DATABASE_BINDING"):self.assemble()

    def test_no_workflow_retry_allowed(self):
        with self.assertRaisesRegex(ValueError,"NEW_RUN_BINDING"):
            backend.assemble(self.prior,self.review,self.c14dir,self.fresh,run_id=999999,run_attempt=2)

    def test_inventory_selection_refuses_additions_duplicates_and_wrong_file_distribution(self):
        for nodes in (self.ids+self.ids[:1],self.ids[:-1],self.ids[:-1]+[self.ids[0]],
                      self.ids[:-1]+["tests/test_unapproved.py::test_x"]):
            with self.subTest(nodes=nodes),self.assertRaises(ValueError):backend.expected_selection(nodes)

    def test_prepare_requires_exact_profile_and_input_bindings(self):
        transport=dict(owner_c="C13",attempt=1,runtime_task_id="new-task",c14_run_id=fixed.C14_RUN,
                       supplement=dict(fixed.ENVELOPE))
        env=dict(RUNTIME_TRANSPORT=json.dumps(transport),GITHUB_RUN_ATTEMPT="1",
            CANDIDATE_SHA=fixed.CANDIDATE,APPLICATION_TREE=fixed.APPLICATION_TREE,
            ISSUE_NUMBER=str(fixed.ISSUE),ROUND_ID=fixed.ROUND,C13_TASK_ID=fixed.C13_TASK,
            C14_TASK_ID=fixed.C14_TASK,MACHINE_INVENTORY=fixed.INVENTORY)
        self.assertTrue(backend.prepare(env))
        for key,value in (("CANDIDATE_SHA","bad"),("MACHINE_INVENTORY","application/tests"),
                          ("GITHUB_RUN_ATTEMPT","2")):
            with self.subTest(key=key),self.assertRaises(ValueError):backend.prepare(dict(env,**{key:value}))
        self.assertFalse(backend.prepare({"RUNTIME_TRANSPORT":"{}"}))


if __name__ == "__main__":unittest.main()
