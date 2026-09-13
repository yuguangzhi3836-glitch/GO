import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('provider_preflight',Path(__file__).resolve().parents[1]/'scripts/provider_certification_preflight.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ProviderInputTests(unittest.TestCase):
    def inputs(self):
        return dict(zip(module.REQUIRED, ['sk_test_fixture_only','https://sandbox.siteminder.com','fixture-id','fixture-secret','{}','fixture-property','{}','{}']))

    def test_missing_inputs_never_certify(self):
        result=module.inspect_inputs({})
        self.assertFalse(result['ready']);self.assertEqual(len(result['missing_required_inputs']),8)
        self.assertEqual(result['external_calls'],0)

    def test_live_payment_key_is_rejected_without_exposing_it(self):
        data=self.inputs();data['STRIPE_TEST_SECRET_KEY']='sk_live_do_not_use'
        result=module.inspect_inputs(data)
        self.assertFalse(result['ready']);self.assertNotIn('sk_live_do_not_use',str(result))

    def test_credential_redirect_and_nonexternal_endpoints_are_rejected(self):
        for field,value in [('STRIPE_API_BASE','https://other.invalid'),
                            ('SITEMINDER_CHANNELS_PLUS_BASE_URL','http://sandbox.siteminder.com'),
                            ('SITEMINDER_CHANNELS_PLUS_BASE_URL','https://key:secret@sandbox.siteminder.com'),
                            ('SITEMINDER_CHANNELS_PLUS_BASE_URL','https://supplier.invalid')]:
            data=self.inputs();data[field]=value;self.assertFalse(module.inspect_inputs(data)['ready'])

    def test_request_fixtures_must_be_json_objects(self):
        for value in ['[1]','null','{invalid']:
            data=self.inputs();data['SITEMINDER_CERT_LOCK_BODY_JSON']=value
            self.assertFalse(module.inspect_inputs(data)['ready'])

    def test_valid_input_structure_remains_uncertified(self):
        result=module.inspect_inputs(self.inputs())
        self.assertTrue(result['ready']);self.assertEqual(result['gate'],'INPUTS_READY_NOT_CERTIFIED')
        self.assertEqual(result['external_certification'],'NOT_RUN');self.assertEqual(result['external_calls'],0)
