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


if __name__ == "__main__":
    unittest.main(verbosity=2)
