"""Offline VERIFY boundary tests. No host access, Docker, keys or signing."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / 'go-hk-deployctl'
spec = importlib.util.spec_from_loader('verify_launcher', importlib.machinery.SourceFileLoader('verify_launcher', str(PATH)))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
IMAGE = 'sha256:' + 'a' * 64
SENTINEL = 'SYNTHETIC_SENSITIVE_DIAGNOSTIC_VALUE'


class VerifyRefusal(unittest.TestCase):
    def setUp(self):
        self.identity = patch.object(launcher, '_installed_identity', return_value={'fixture': True})
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.collect = Mock(return_value={'target_service_count': 8, 'application_health_proven_count': 0})
        self.loader = patch.object(launcher, '_load_collector', return_value=SimpleNamespace(_collect_verify=self.collect))
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def verify(self, **kw):
        return launcher._verify('offline-review', IMAGE, IMAGE, runner=object(), inputs=object(), sleeper=lambda _: None, **kw)

    def refusal(self, error, expected):
        self.collect.side_effect = error
        out, rc = self.verify()
        self.assertEqual(rc, 2)
        self.assertEqual(out['status'], 'REJECTED')
        self.assertEqual(out['result'], 'VERIFY_REJECTED')
        self.assertEqual(out['error_code'], expected)
        self.assertNotIn('installed_identity', out)
        self.assertNotIn(SENTINEL, json.dumps(out))
        return out

    def test_success_shape_unchanged(self):
        out, rc = self.verify()
        self.assertEqual(rc, 0)
        self.assertEqual(out['result'], 'VERIFY_OK')
        self.assertEqual(out['installed_identity'], {'fixture': True})
        self.assertNotIn('error_code', out)
        self.assertFalse(out['gate_results']['application_health_proven'])

    def test_known_collector_reasons(self):
        for message in ('compose baseline', 'env baseline', 'api gate', 'state', 'revision drift', 'inspect parse'):
            with self.subTest(message=message):
                self.refusal(ValueError(message), 'E_VERIFY_' + message.upper().replace(' ', '_'))

    def test_os_path_does_not_leave_boundary(self):
        self.refusal(FileNotFoundError(2, 'missing', '/private/' + SENTINEL), 'E_VERIFY_COLLECT_OS_ERROR')

    def test_untrusted_value_is_not_an_error_code(self):
        self.refusal(ValueError('Authorization: Bearer ' + SENTINEL), 'E_VERIFY_COLLECT_VALUE_ERROR')

    def test_type_error_is_bounded(self):
        self.refusal(TypeError(SENTINEL), 'E_VERIFY_COLLECT_TYPE_ERROR')

    def test_known_message_plus_secret_is_not_whitelisted(self):
        self.refusal(ValueError('env baseline ' + SENTINEL), 'E_VERIFY_COLLECT_VALUE_ERROR')

    def test_installation_suffix_is_removed(self):
        self.refusal(ValueError('E_INSTALL_FACT_MODULE_DRIFT:' + SENTINEL), 'E_INSTALL_FACT_MODULE_DRIFT')

    def test_unknown_installation_code_is_not_exported(self):
        self.refusal(ValueError('E_INSTALL_FACT_' + SENTINEL), 'E_VERIFY_COLLECT_VALUE_ERROR')

    def test_installation_failure_stops_before_collector(self):
        with patch.object(launcher, '_installed_identity', side_effect=OSError(SENTINEL)):
            out, rc = self.verify()
        self.assertEqual((rc, out['error_code']), (2, 'E_VERIFY_INSTALLATION_OS_ERROR'))
        self.collect.assert_not_called()
        self.assertNotIn(SENTINEL, json.dumps(out))

    def test_collector_load_failure_has_own_stage(self):
        with patch.object(launcher, '_load_collector', side_effect=ValueError(SENTINEL)):
            out, rc = self.verify()
        self.assertEqual((rc, out['error_code']), (2, 'E_VERIFY_COLLECTOR_LOAD_VALUE_ERROR'))
        self.collect.assert_not_called()

    def test_input_refusal_stops_collection(self):
        out, rc = launcher._verify(SENTINEL + '/', IMAGE, IMAGE)
        self.assertEqual((rc, out['error_code']), (2, 'E_VERIFY_RELEASE_ID'))
        self.collect.assert_not_called()

    def test_wrong_service_count_remains_rejected(self):
        self.collect.return_value['target_service_count'] = 9
        out, rc = self.verify()
        self.assertEqual((rc, out['error_code']), (2, 'E_VERIFY_COLLECTOR_RESULT'))


if __name__ == '__main__':
    unittest.main()
