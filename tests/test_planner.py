import io
import sys
import unittest

from agent.planner import PLANNER_PROMPT, _safe_print


class PlannerPromptTests(unittest.TestCase):
    def test_planner_prompt_includes_voice_telegram_parity_tools(self):
        self.assertIn("self_modifier", PLANNER_PROMPT)
        self.assertIn("persona_control", PLANNER_PROMPT)
        self.assertIn("paperclip_control", PLANNER_PROMPT)
        self.assertIn("openfang_control", PLANNER_PROMPT)
        self.assertIn("symphony_control", PLANNER_PROMPT)
        self.assertIn("lossless_claw_control", PLANNER_PROMPT)
        self.assertIn("computer_use", PLANNER_PROMPT)
        self.assertIn("crucix_control", PLANNER_PROMPT)
        self.assertIn("gemini_native", PLANNER_PROMPT)
        self.assertIn("planning-with-files workflow", PLANNER_PROMPT)
        self.assertIn("OpenManus-style orchestration guidance", PLANNER_PROMPT)

    def test_safe_print_handles_cp1252_streams(self):
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="cp1252")
        original_stdout = sys.stdout
        try:
            sys.stdout = stdout
            _safe_print("[Planner] unicode fallback \U0001f9e0")
            stdout.flush()
        finally:
            sys.stdout = original_stdout

        rendered = buffer.getvalue().decode("cp1252")
        self.assertIn("[Planner] unicode fallback", rendered)


if __name__ == "__main__":
    unittest.main()
