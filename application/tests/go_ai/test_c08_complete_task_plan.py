"""Pure planner regression tests; no model calls, database or provider stubs."""
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import types
import unittest


# Load the real pure modules without go_ai.__init__ starting the global service.
SOURCE = Path(__file__).resolve().parents[2] / "src/go_hotel/go_ai"
PACKAGE = "_c08_complete_plan_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(SOURCE)]
sys.modules[PACKAGE] = package


def load_module(name):
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", SOURCE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


complexity = load_module("complexity")
planner = load_module("planner")


class CompleteTaskPlanTests(unittest.TestCase):
    def setUp(self):
        self.classifier = complexity.GOAIComplexityClassifier()
        self.planner = planner.GOAITaskPlanner()
        self.message = "比较酒店、机票、火车、接送、景点和预算，同时评估退款风险"

    def test_high_assurance_keeps_all_verticals_constraints_and_risk(self):
        assessment = self.classifier.classify(self.message)
        self.assertEqual(assessment.tier, "TIER_5_HIGH_ASSURANCE")
        tasks = self.planner.plan(self.message, assessment)
        self.assertEqual({t.task_id for t in tasks}, {
            "task_hotel", "task_flight", "task_rail", "task_mobility",
            "task_attraction", "task_budget", "task_constraints",
            "task_reasoning", "task_risk",
        })
        self.assertTrue(all(t.required for t in tasks))
        self.assertTrue(all(self.message in t.instruction for t in tasks))
        self.assertIn("Advisory only", next(t.instruction for t in tasks if t.task_id == "task_risk"))

    def test_low_concurrency_does_not_remove_required_work(self):
        assessment = self.classifier.classify(self.message)
        expected = self.planner.plan(self.message, assessment)
        for limit in (1, 2, 4, 6):
            with self.subTest(limit=limit):
                self.assertEqual(self.planner.plan(self.message, replace(assessment, max_parallel_tasks=limit)), expected)

    def test_deep_reasoning_keeps_constraints_after_six_verticals(self):
        assessment = replace(self.classifier.classify(self.message), tier="TIER_3_DEEP_REASONING")
        tasks = self.planner.plan(self.message, assessment)
        self.assertEqual(len(tasks), 8)
        self.assertIn("task_constraints", [t.task_id for t in tasks])
        self.assertIn("task_reasoning", [t.task_id for t in tasks])

    def test_repeated_keywords_are_bounded_and_stable(self):
        assessment = self.classifier.classify(self.message)
        tasks = self.planner.plan(self.message * 100, assessment)
        self.assertEqual(len(tasks), 9)
        self.assertEqual(len({t.task_id for t in tasks}), 9)
        self.assertEqual(tasks, self.planner.plan(self.message * 100, assessment))

    def test_simple_and_deterministic_paths_unchanged(self):
        assessment = self.classifier.classify("你好")
        self.assertEqual([t.task_id for t in self.planner.plan("你好", assessment)], ["task_main"])
        deterministic = self.classifier.classify(self.message, context={"deterministic_only": True})
        self.assertEqual(self.planner.plan(self.message, deterministic), [])

    def test_single_vertical_retains_original_order(self):
        assessment = self.classifier.classify("酒店退款")
        self.assertEqual([t.task_id for t in self.planner.plan("酒店退款", assessment)],
                         ["task_hotel", "task_constraints", "task_reasoning", "task_risk"])


if __name__ == "__main__":
    unittest.main()
