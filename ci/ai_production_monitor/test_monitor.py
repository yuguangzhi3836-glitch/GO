#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import monitor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
        self.sha1 = "a" * 40
        self.sha2 = "b" * 40

    def record(self, role, sha, verdict, hours_ago=1):
        return monitor.ReviewRecord(
            role=role,
            candidate_sha=sha,
            verdict=verdict,
            issued_at=self.now - timedelta(hours=hours_ago),
        )

    def test_summary_counts_candidate_and_full_pass_without_claiming_first_pass(self):
        records = [
            self.record("c14", self.sha1, "PASS_SCOPED"),
            self.record("c13", self.sha1, "PASS_SCOPED"),
            self.record("c14", self.sha2, "BLOCKED"),
        ]
        summary = monitor.summarize(records, self.now)
        seven = summary["7 days"]
        self.assertEqual(seven["candidate_count"], 2)
        self.assertEqual(seven["full_pass_candidates"], 1)
        self.assertEqual(seven["c14_pass"], 1)
        self.assertEqual(seven["c14_blocked"], 1)
        self.assertEqual(seven["c13_pass"], 1)

        rendered = monitor.render_live_metrics(summary, self.now, "Asia/Shanghai", [])
        self.assertIn("FIRST_PASS_RATE = NOT_YET_AVAILABLE", rendered)
        self.assertIn("REWORK_DEPTH = NOT_YET_AVAILABLE", rendered)

    def test_c14_not_applicable_is_passlike_for_full_chain(self):
        records = [
            self.record("c14", self.sha1, "NOT_APPLICABLE"),
            self.record("c13", self.sha1, "PASS_SCOPED"),
        ]
        summary = monitor.summarize(records, self.now)
        self.assertEqual(summary["30 days"]["full_pass_candidates"], 1)
        self.assertEqual(summary["30 days"]["c14_na"], 1)

    def test_today_uses_business_timezone(self):
        now = datetime(2026, 9, 26, 16, 30, tzinfo=timezone.utc)
        earlier = monitor.ReviewRecord(
            role="c14",
            candidate_sha=self.sha1,
            verdict="PASS_SCOPED",
            issued_at=datetime(2026, 9, 26, 15, 59, tzinfo=timezone.utc),
        )
        later = monitor.ReviewRecord(
            role="c14",
            candidate_sha=self.sha2,
            verdict="PASS_SCOPED",
            issued_at=datetime(2026, 9, 26, 16, 1, tzinfo=timezone.utc),
        )
        summary = monitor.summarize([earlier, later], now, "Asia/Shanghai")
        self.assertEqual(summary["Today"]["candidate_count"], 1)

    def test_replace_only_marked_section(self):
        old = f"before\n{monitor.START_MARKER}\nold\n{monitor.END_MARKER}\nafter"
        new = f"{monitor.START_MARKER}\nnew\n{monitor.END_MARKER}"
        result = monitor.replace_marked_section(old, new)
        self.assertEqual(result, "before\n" + new + "\nafter")

    def test_bundle_reader_finds_nested_bundle(self):
        payload = {
            "cell_id": "C14",
            "candidate_sha": self.sha1,
            "verdict": "PASS_SCOPED",
            "issued_at": "2026-09-26T00:00:00Z",
        }
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("nested/c14_bundle.json", json.dumps(payload))
        self.assertEqual(monitor._bundle_from_zip(buf.getvalue(), "c14"), payload)

    def test_poc_only_artifact_is_not_production_evidence(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("poc.json", '{"round_id":"POC_ONLY"}')
            archive.writestr("logs/poc.spec.json", '{"candidate_sha":"' + ("f" * 40) + '"}')
        with self.assertRaises(monitor.NonProductionArtifact):
            monitor._bundle_from_zip(buf.getvalue(), "c14")


    def _sealed_artifact_zip(self, role, sha, verdict, run_id):
        payload = {
            "cell_id": role.upper(),
            "candidate_sha": sha,
            "verdict": verdict,
            "issued_at": "2026-09-26T00:00:00Z",
            "github_run_id": run_id,
        }
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr(f"{role}_bundle.json", json.dumps(payload))
        return buf.getvalue()

    def test_collect_records_includes_only_main_workflow_dispatch_runs(self):
        formal_run = 101
        test_push_run = 102
        test_dispatch_run = 103
        artifacts = [
            {
                "id": 201,
                "name": f"c13c14-lite-c14-{self.sha1}",
                "created_at": "2026-09-26T00:00:00Z",
                "workflow_run": {"id": formal_run},
            },
            {
                "id": 202,
                "name": f"c13c14-lite-c14-{self.sha2}",
                "created_at": "2026-09-26T00:00:00Z",
                "workflow_run": {"id": test_push_run},
            },
            {
                "id": 203,
                "name": f"c13c14-lite-c14-{'c' * 40}",
                "created_at": "2026-09-26T00:00:00Z",
                "workflow_run": {"id": test_dispatch_run},
            },
        ]
        bundles = {
            201: self._sealed_artifact_zip("c14", self.sha1, "PASS_SCOPED", formal_run),
            202: self._sealed_artifact_zip("c14", self.sha2, "PASS_SCOPED", test_push_run),
            203: self._sealed_artifact_zip("c14", "c" * 40, "PASS_SCOPED", test_dispatch_run),
        }

        class FakeAPI:
            def __init__(self):
                self.downloaded = []
                self.runs = {
                    formal_run: {"head_branch": "main", "event": "workflow_dispatch"},
                    test_push_run: {
                        "head_branch": "test/c14-r1-replay-20260927",
                        "event": "push",
                    },
                    test_dispatch_run: {
                        "head_branch": "test/c14-r1-replay-20260927",
                        "event": "workflow_dispatch",
                    },
                }

            def list_recent_artifacts(self, cutoff):
                return artifacts

            def get_workflow_run(self, run_id):
                return self.runs[run_id]

            def download_artifact(self, artifact_id):
                self.downloaded.append(artifact_id)
                return bundles[artifact_id]

        api = FakeAPI()
        records, warnings = monitor.collect_records(
            api, datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(warnings, [])
        self.assertEqual([(r.role, r.candidate_sha, r.verdict) for r in records], [
            ("c14", self.sha1, "PASS_SCOPED"),
        ])
        self.assertEqual(api.downloaded, [201])

    def test_collect_records_fails_closed_when_artifact_has_no_run_identity(self):
        artifact = {
            "id": 301,
            "name": f"c13c14-lite-c14-{self.sha1}",
            "created_at": "2026-09-26T00:00:00Z",
        }

        class FakeAPI:
            def list_recent_artifacts(self, cutoff):
                return [artifact]

            def get_workflow_run(self, run_id):
                raise AssertionError("run lookup must not happen without a run id")

            def download_artifact(self, artifact_id):
                raise AssertionError("unattributed artifact must not be downloaded")

        records, warnings = monitor.collect_records(
            FakeAPI(), datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(records, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("workflow run identity missing; excluded", warnings[0])

    def test_boss_activity_links_formal_task_to_builder_and_keeps_review_block_out_of_runtime(self):
        now = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
        issues = [
            {
                "number": 522,
                "title": "C11 · V86-R1-C11-01 · 补偿结算恢复收据冲突拒绝",
                "body": "Task: scoped work",
                "created_at": "2026-10-07T02:00:00Z",
                "user": {"login": "yuguangzhi3836-glitch"},
            },
            {
                "number": 999,
                "title": "C01 · V99-R1-C01-01 · other user task",
                "body": "Task: ignore",
                "created_at": "2026-10-07T02:10:00Z",
                "user": {"login": "someone-else"},
            },
        ]
        pulls = [
            {
                "number": 527,
                "title": "[Builder] C11 settlement replay",
                "body": "Work order: V86-R1-C11-01\nIssue: #522",
                "updated_at": "2026-10-07T03:00:00Z",
                "head": {"sha": self.sha1},
                "state": "open",
                "draft": True,
            }
        ]
        records = [
            monitor.ReviewRecord("c14", self.sha1, "PASS_SCOPED", datetime(2026, 10, 7, 3, 10, tzinfo=timezone.utc)),
            monitor.ReviewRecord("c13", self.sha1, "BLOCKED", datetime(2026, 10, 7, 3, 20, tzinfo=timezone.utc)),
        ]
        activity = monitor.build_boss_activity(
            issues, pulls, records, now, "Asia/Shanghai", "yuguangzhi3836-glitch"
        )
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]["candidate_number"], 527)
        self.assertEqual(activity[0]["status"], "PRODUCT_OR_REVIEW_BLOCKED")
        rendered = "\n".join(monitor.render_boss_activity(activity, "yuguangzhi3836-glitch", []))
        self.assertIn("RUNTIME_ACTION_REQUIRED = NO_PROVEN_GENERIC_FAILURE", rendered)
        self.assertIn("AUTO_REPAIR_RUNTIME = NO", rendered)

    def test_boss_activity_includes_manual_c14_review_and_c13_result(self):
        now = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
        issues = [{
            "number": 533,
            "title": "C14 · REVIEW · payment recovery review",
            "body": "Candidate PR: #531\nCandidate SHA: " + self.sha2,
            "created_at": "2026-10-07T05:00:00Z",
            "user": {"login": "yuguangzhi3836-glitch"},
        }]
        pulls = [{
            "number": 531,
            "title": "candidate",
            "body": "",
            "updated_at": "2026-10-07T05:00:00Z",
            "head": {"sha": self.sha2},
            "state": "open",
            "draft": True,
        }]
        records = [
            monitor.ReviewRecord("c14", self.sha2, "PASS_SCOPED", datetime(2026, 10, 7, 5, 10, tzinfo=timezone.utc)),
            monitor.ReviewRecord("c13", self.sha2, "PASS_SCOPED", datetime(2026, 10, 7, 5, 20, tzinfo=timezone.utc)),
        ]
        activity = monitor.build_boss_activity(
            issues, pulls, records, now, "Asia/Shanghai", "yuguangzhi3836-glitch"
        )
        self.assertEqual(activity[0]["cell"], "C14")
        self.assertEqual(activity[0]["candidate_number"], 531)
        self.assertEqual(activity[0]["status"], "REVIEW_ACCEPTED")

    def test_local_day_start_uses_business_timezone(self):
        now = datetime(2026, 10, 7, 3, 59, tzinfo=timezone.utc)
        self.assertEqual(
            monitor._local_day_start(now, "Asia/Shanghai"),
            datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc),
        )



if __name__ == "__main__":
    unittest.main(verbosity=2)
