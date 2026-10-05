import importlib.util
from pathlib import Path
import json
import unittest

spec = importlib.util.spec_from_file_location('receipt', Path(__file__).with_name('write_stage_receipt.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class StageReceiptTests(unittest.TestCase):
    def test_first_failure_is_ordered_and_outputs_are_not_copied(self):
        report = module.receipt({'stage_03': {'outcome':'skipped'},
            'stage_02': {'outcome':'failure','outputs':{'secret':'NEVER_COPY'}},
            'stage_01': {'outcome':'failure'}})
        self.assertEqual(report['first_failed_stage'], 'stage_01')
        self.assertEqual(report['status'], 'FAIL')
        self.assertNotIn('NEVER_COPY', json.dumps(report))
    def test_no_failure_is_not_acceptance(self):
        report = module.receipt({'stage_01': {'outcome':'success'}})
        self.assertFalse(report['acceptance_pass'])
        self.assertEqual(report['status'], 'NO_PRIOR_STEP_FAILURE')

if __name__ == '__main__':
    unittest.main()
