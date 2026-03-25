import unittest

from agent.planner import PLANNER_PROMPT


class PlannerPromptTests(unittest.TestCase):
    def test_planner_prompt_includes_voice_telegram_parity_tools(self):
        self.assertIn("self_modifier", PLANNER_PROMPT)
        self.assertIn("persona_control", PLANNER_PROMPT)
        self.assertIn("paperclip_control", PLANNER_PROMPT)
        self.assertIn("openfang_control", PLANNER_PROMPT)
        self.assertIn("symphony_control", PLANNER_PROMPT)
        self.assertIn("lossless_claw_control", PLANNER_PROMPT)


if __name__ == "__main__":
    unittest.main()
