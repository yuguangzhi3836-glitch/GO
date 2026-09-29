"""A refusal remains a refusal while harmless failure metadata survives."""
import argparse
import hashlib
import json
import pathlib
import re
import tempfile
import unittest

import lite_cli
import lite_failure_diagnostic as diagnostic
import lite_prerequisite


class FailureDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def put(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def build(self, outcome):
        spec = self.put('spec.json', {'role': 'c14', 'run_id': 123, 'candidate_sha': 'a'*40,
                                      'application_tree': 'b'*40})
        source = self.put('outcome.json', outcome)
        seal = self.put('seal.json', {'status': 'REFUSED', 'exit_code': 2})
        original = source.read_bytes()
        output = diagnostic.build(spec, source, seal)
        self.assertEqual(source.read_bytes(), original)
        result = json.loads(output)
        self.assertEqual(result['sources']['outcome']['sha256'], hashlib.sha256(original).hexdigest())
        self.assertTrue(result['diagnostic_only'])
        self.assertTrue(result['not_acceptance_evidence'])
        self.assertFalse(result['c13_prerequisite_eligible'])
        self.assertFalse(result['authorizes_any_action'])
        self.assertFalse(result['original_content_included'])
        return output, result

    def test_quota_with_key_shaped_message_keeps_only_typed_metadata(self):
        token = 'sk-' + 'syntheticA1' * 5
        output, result = self.build({'verdict': 'BLOCKED', 'failure_class': 'AI_QUOTA_EXHAUSTED',
            'http_status': 429, 'ai_called': True, 'detail': json.dumps({'error': {
                'code': 'insufficient_quota', 'message': 'no credits remaining ' + token}}),
            'review_trace': {'complete': False, 'plan': {'parts': [{}, {}]},
                             'parts': [{'response_json': token}, {'error': {'detail': token}}]}})
        self.assertNotIn(token.encode(), output)
        self.assertEqual(result['provider_error_code'], 'insufficient_quota')
        self.assertEqual(result['http_status'], 429)
        self.assertEqual(result['failure_class'], 'AI_QUOTA_EXHAUSTED')
        self.assertEqual(result['recorded_response_count'], 1)
        self.assertEqual(result['recorded_error_count'], 1)
        self.assertEqual(result['seal_status'], 'REFUSED')
        self.assertIn('openai_key', result['sources']['outcome']['secret_shape_labels'])

    def test_each_secret_family_and_unknown_fields_are_omitted(self):
        secrets = ['sk-'+'a'*25, '-----BEGIN '+'PRIVATE KEY-----',
                   'github_pat_'+'b'*25, 'ghp_'+'c'*25, 'AKIA'+'D'*16,
                   'LTAI'+'e'*20, 'Bearer '+'f'*25]
        for token in secrets:
            with self.subTest(family=token[:4]):
                output, _ = self.build({'detail': token, token: token,
                    'opinion': {'summary': token}, 'unknown': {'value': token}})
                self.assertNotIn(token.encode(), output)
                for _, pattern in lite_cli.FORBIDDEN_SECRET_PATTERNS:
                    self.assertIsNone(re.search(pattern, output))

    def test_malicious_values_in_allowlisted_fields_are_not_copied(self):
        token = 'Bearer '+'A'*30
        output, result = self.build({'verdict': token, 'failure_class': [token],
            'http_status': True, 'ai_called': token, 'detail': json.dumps({'error': {'code': token}}),
            'review_trace': {'parts': token, 'plan': token, 'complete': token}})
        self.assertNotIn(token.encode(), output)
        self.assertIsNone(result['failure_class'])
        self.assertIsNone(result['reported_verdict'])
        self.assertIsNone(result['http_status'])
        self.assertFalse(result['ai_called'])
        self.assertFalse(result['trace_complete'])

    def test_missing_and_malformed_sources_remain_diagnostic(self):
        broken = self.root / 'bad.json'
        broken.write_bytes(b'not json sk-' + b'A'*30)
        output = diagnostic.build(self.root/'missing.json', broken)
        result = json.loads(output)
        self.assertFalse(result['sources']['spec']['present'])
        self.assertIsNone(result['reported_verdict'])
        self.assertIn('openai_key', result['sources']['outcome']['secret_shape_labels'])
        self.assertNotIn(b'A'*30, output)

    def test_reported_pass_never_becomes_a_c13_prerequisite(self):
        _, result = self.build({'verdict': 'PASS_SCOPED', 'review_trace': {'complete': True}})
        with self.assertRaises(Exception):
            lite_prerequisite.evaluate(result, candidate_sha='a'*40)

    def test_raw_secret_guard_still_refuses_after_diagnostic_is_written(self):
        token = 'sk-'+'A'*30
        self.build({'detail': token})
        args = argparse.Namespace(out=str(self.root/'raw'), spec=None, facts=None, contract=None,
            outcome=str(self.root/'outcome.json'), scope=None, review_brief=None,
            seal_result=None, seal_stdout=None, seal_stderr=None)
        with self.assertRaises(SystemExit):
            lite_cli.cmd_raw_evidence(args)
        self.assertFalse((self.root/'raw').exists())

    def test_workflows_publish_diagnostics_on_failure_without_ai_credentials(self):
        import yaml
        repo = pathlib.Path(__file__).resolve().parents[2]
        for role, filename in [('c14','c14-rule-compliance.yml'), ('c13','c13-quality-acceptance.yml')]:
            document = yaml.safe_load((repo/'.github/workflows'/filename).read_text())
            job = document['jobs']['c14-rule-review' if role == 'c14' else 'c13-ai-review']
            steps = job['steps']
            build = next(s for s in steps if 'lite_failure_diagnostic.py' in s.get('run',''))
            publish = next(s for s in steps if s.get('with',{}).get('name','').startswith('c13c14-lite-'+role+'-diagnostic-'))
            self.assertEqual(build['if'], 'always()')
            self.assertEqual(publish['if'], 'always()')
            self.assertNotIn('OPENAI_API_KEY', json.dumps(build))
            self.assertNotIn('OPENAI_API_KEY', json.dumps(publish))
            self.assertNotEqual(publish['with']['path'], '${{ runner.temp }}/artifacts')


if __name__ == '__main__':
    unittest.main()
