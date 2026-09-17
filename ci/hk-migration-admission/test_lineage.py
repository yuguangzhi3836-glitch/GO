import unittest
from lineage import Refused, forward_path

def graph(**edges):
    return {name: {'parents': parents} for name, parents in edges.items()}

class LineageTests(unittest.TestCase):
    def test_merge_retains_both_branches(self):
        g=graph(base=(), left=('base',), right=('base',), merge=('left','right'), head=('merge',))
        self.assertEqual(forward_path(g,'base','head'),['left','right','merge','head'])
    def test_same_revision_needs_no_migration(self):
        self.assertEqual(forward_path(graph(base=()),'base','base'),[])
    def test_missing_parent(self):
        with self.assertRaisesRegex(Refused,'MISSING_PARENT'):
            forward_path(graph(base=(),head=('missing','base')),'base','head')
    def test_multiple_heads(self):
        with self.assertRaisesRegex(Refused,'SINGLE_EXPECTED_HEAD_REQUIRED'):
            forward_path(graph(base=(),head=('base',),other=('base',)),'base','head')
    def test_cycle_is_refused(self):
        with self.assertRaisesRegex(Refused,'MIGRATION_CYCLE'):
            forward_path(graph(base=(),a=('b',),b=('a',),head=('base','a')),'base','head')
    def test_baseline_must_precede_target(self):
        with self.assertRaises(Refused):
            forward_path(graph(base=('head',),head=()),'base','head')

if __name__ == '__main__':
    unittest.main()
