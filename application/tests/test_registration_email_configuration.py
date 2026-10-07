"""Isolated SMTP configuration regression tests; no database or network needed.

Run with: python -m unittest discover -s application/tests -p test_registration_email_configuration.py -v
Only the settings dependency is replaced; the real service source is executed.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class RegistrationEmailConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.secret = root / 'password'
        self.secret.write_text('isolated-password\r\n')
        self.config = root / 'smtp.json'
        settings_module = ModuleType('go_hotel.core.config')
        self.settings = settings_module.settings = SimpleNamespace(
            registration_email_config_path=str(self.config),
            registration_verification_enabled=True,
        )
        source = Path(__file__).resolve().parents[1] / 'src/go_hotel/services/registration_email.py'
        spec = importlib.util.spec_from_file_location('isolated_registration_email', source)
        self.mail = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'go_hotel.core.config': settings_module}):
            spec.loader.exec_module(self.mail)
        self.smtp = self.enterContext(patch.object(self.mail.smtplib, 'SMTP'))
        self.ssl_smtp = self.enterContext(patch.object(self.mail.smtplib, 'SMTP_SSL'))
        self.valid = dict(sender=self.mail.SENDER,
                          credential_reference='hk-staging-registration-email',
                          tls='STARTTLS', host='smtp.test.invalid', port=587,
                          username=self.mail.SENDER, password_file=str(self.secret))

    def write(self, value):
        self.config.write_text(json.dumps(value))

    def assert_not_ready(self):
        with self.assertRaisesRegex(ValueError, '^REGISTRATION_VERIFICATION_NOT_READY$'):
            self.mail.configuration()
        self.assertIs(self.mail.ready(), False)
        with self.assertRaisesRegex(ValueError, '^REGISTRATION_VERIFICATION_NOT_READY$'):
            self.mail.send_code('recipient@example.test', '123456')
        self.smtp.assert_not_called()
        self.ssl_smtp.assert_not_called()

    def test_non_object_json_is_not_ready(self):
        for value in (None, [], ['smtp'], 'smtp', 42, True):
            with self.subTest(value=value):
                self.write(value)
                self.assert_not_ready()

    def test_invalid_port_is_not_ready(self):
        for port in (True, False, 0, 65536, '587', 587.0, None):
            with self.subTest(port=port):
                self.write(self.valid | {'port': port})
                self.assert_not_ready()

    def test_host_and_username_require_nonblank_strings(self):
        for field in ('host', 'username'):
            for value in (True, 42, ['smtp'], {'value': 'smtp'}, '', ' \t\n', None):
                with self.subTest(field=field, value=value):
                    self.write(self.valid | {field: value})
                    self.assert_not_ready()

    def test_fixed_sender_credential_and_tls_remain_required(self):
        for field, value in (('sender', 'other@example.test'),
                             ('credential_reference', 'other-account'),
                             ('tls', 'NONE')):
            with self.subTest(field=field):
                self.write(self.valid | {field: value})
                self.assert_not_ready()

    def test_missing_fields_are_not_ready(self):
        for field in self.valid:
            with self.subTest(field=field):
                self.write({key: value for key, value in self.valid.items() if key != field})
                self.assert_not_ready()

    def test_unreadable_or_empty_secret_is_not_ready(self):
        for secret in ('relative-secret', str(self.secret.parent / 'missing'), None, 42):
            with self.subTest(secret=secret):
                self.write(self.valid | {'password_file': secret})
                self.assert_not_ready()
        self.secret.write_text('')
        self.write(self.valid)
        self.assert_not_ready()

    def test_bad_config_file_is_not_ready(self):
        self.assert_not_ready()
        self.config.write_text('{broken')
        self.assert_not_ready()
        self.settings.registration_email_config_path = ''
        self.assert_not_ready()

    def test_valid_tls_and_boundary_ports_remain_ready(self):
        for tls in ('STARTTLS', 'SSL'):
            for port in (1, 465, 587, 65535):
                with self.subTest(tls=tls, port=port):
                    expected = self.valid | {'tls': tls, 'port': port}
                    self.write(expected)
                    self.assertEqual(self.mail.configuration(), (expected, 'isolated-password'))
                    self.assertIs(self.mail.ready(), True)
        self.smtp.assert_not_called()
        self.ssl_smtp.assert_not_called()

    def test_disabled_flag_remains_not_ready(self):
        self.write(self.valid)
        self.settings.registration_verification_enabled = False
        self.assertIs(self.mail.ready(), False)


if __name__ == '__main__':
    unittest.main()
