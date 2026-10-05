"""Closed, unmerged candidates must remain reviewable without reopening CI."""
import io
import json
import unittest
from unittest.mock import patch
import urllib.error

import lite_review_brief as brief

SHA = "a" * 40


def pr(number, sha=SHA):
    return {"number": number, "head": {"sha": sha}, "state": "closed",
            "base": {"ref": "main"}, "body": "NO-GO; review only"}


class ClosedBriefTests(unittest.TestCase):
    def resolve(self, pages, limit=20):
        requests = []
        responses = iter(pages)
        def open_request(request, **kwargs):
            requests.append(request)
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return io.BytesIO(json.dumps(response).encode())
        with patch.object(brief.urllib.request, "urlopen", open_request), \
                patch.object(brief, "MAX_CLOSED_PAGES", limit):
            result = brief.resolve(SHA, brief.github_pull_reader("o/r", "test-only"))
        self.assertTrue(all(r.get_method() == "GET" for r in requests))
        return result, [r.full_url for r in requests]

    def test_closed_unmerged_head_preserves_brief(self):
        result, urls = self.resolve([[], [pr(440)]])
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["pull_request"]["number"], 440)
        self.assertEqual(result["pull_request"]["body"], "NO-GO; review only")
        self.assertIn("state=closed", urls[1])

    def test_scan_continues_past_full_page(self):
        result, urls = self.resolve([[], [pr(i + 1, "b" * 40) for i in range(100)], [pr(440)]])
        self.assertEqual(result["status"], "OK")
        self.assertIn("page=2", urls[-1])

    def test_duplicate_on_later_page_is_not_hidden_by_first_match(self):
        result, _ = self.resolve([[], [pr(440)] + [pr(i + 1, "b" * 40) for i in range(99)], [pr(441)]])
        self.assertEqual(result["reason"], brief.PR_AMBIGUOUS)

    def test_incomplete_scan_refuses_even_with_a_match(self):
        result, _ = self.resolve([[], [pr(440)] * 100], limit=1)
        self.assertEqual(result["reason"], brief.PR_AMBIGUOUS)

    def test_transport_failure_does_not_accept_partial_match(self):
        result, _ = self.resolve([[], [pr(440)] * 100, OSError("offline")])
        self.assertEqual(result["reason"], brief.PR_UNREADABLE)

    def test_invalid_closed_response_refuses(self):
        result, _ = self.resolve([[], {}])
        self.assertEqual(result["reason"], brief.PR_UNREADABLE)

    def test_malformed_entry_alongside_match_refuses(self):
        bad = [None, "not-a-pr", {}, dict(pr(441), head="bad"),
               dict(pr(441), head={}), dict(pr(441), number=True),
               dict(pr(441), number=0), dict(pr(441), state="open"),
               dict(pr(441), merge_commit_sha="bad")]
        for item in bad:
            with self.subTest(item=item):
                result, _ = self.resolve([[], [pr(440), item]])
                self.assertEqual(result["reason"], brief.PR_UNREADABLE)
                self.assertIsNone(result["pull_request"])

    def test_malformed_later_page_invalidates_prior_match(self):
        result, _ = self.resolve([[], [pr(440)] * 100, [None]])
        self.assertEqual(result["reason"], brief.PR_UNREADABLE)
        self.assertIsNone(result["pull_request"])

    def test_absent_sha_stays_not_found(self):
        result, _ = self.resolve([[], [pr(440, "b" * 40)]])
        self.assertEqual(result["reason"], brief.PR_NOT_FOUND)

    def test_existing_association_unchanged(self):
        result, urls = self.resolve([[pr(440)]])
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(urls), 1)

    def test_existing_ambiguity_unchanged(self):
        result, urls = self.resolve([[pr(440), pr(441)]])
        self.assertEqual(result["reason"], brief.PR_AMBIGUOUS)
        self.assertEqual(len(urls), 1)

    def test_existing_full_page_refusal_unchanged(self):
        result, _ = self.resolve([[pr(440)] * 100])
        self.assertEqual(result["reason"], brief.PR_AMBIGUOUS)


if __name__ == "__main__":
    unittest.main()
