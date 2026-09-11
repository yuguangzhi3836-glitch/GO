import unittest

from task_routing import TaskRoutingValidationError, validate_model_envelope, validate_task_draft


def draft():
    return {
        "title": "核对 Staging 健康状态",
        "objective": "形成只读状态摘要。",
        "task_type": "status_review",
        "scope_in": ["已有 Evidence"],
        "scope_out": ["任何环境修改"],
        "constraints": ["COMMAND_ONLY"],
        "acceptance_criteria": ["输出已验证与 HOLD 项"],
        "complexity": "L1",
        "risk": "low",
        "domains": ["operations"],
        "recommended_model_alias": "deepseek-v4-pro",
        "recommended_reasoning_level": "high",
        "agent_plan": [{"role": "总指挥", "objective": "汇总状态", "deliverables": ["状态摘要"]}],
        "requires_human_approval": True,
        "reason_summary": "只读讨论任务。",
    }


class TaskRoutingContractTests(unittest.TestCase):
    def test_candidate_requires_exact_contract(self):
        envelope = {
            "message_type": "task_candidate",
            "assistant_reply": "已生成任务草稿，等待确认。",
            "task_draft": draft(),
        }
        self.assertEqual(validate_model_envelope(envelope)["task_draft"]["complexity"], "L1")

    def test_extra_fields_are_rejected(self):
        value = draft()
        value["shell_command"] = "do not run"
        with self.assertRaises(TaskRoutingValidationError):
            validate_task_draft(value)

    def test_human_approval_cannot_be_false(self):
        value = draft()
        value["requires_human_approval"] = False
        with self.assertRaises(TaskRoutingValidationError):
            validate_task_draft(value)

    def test_discussion_cannot_carry_hidden_draft(self):
        envelope = {"message_type": "discussion", "assistant_reply": "普通讨论。", "task_draft": draft()}
        with self.assertRaises(TaskRoutingValidationError):
            validate_model_envelope(envelope)


if __name__ == "__main__":
    unittest.main()
