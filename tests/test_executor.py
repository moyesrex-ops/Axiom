import unittest
from unittest.mock import patch

from agent.executor import AgentExecutor


class ExecutorDirectRouteTests(unittest.TestCase):
    def test_direct_route_handles_rgb_goal_without_planner(self):
        executor = AgentExecutor()

        with patch("agent.executor.create_plan") as create_plan_mock, patch(
            "agent.executor._call_tool",
            return_value="Hardware RGB updated: ASUS TUF Laptop Keyboard: color=green.",
        ) as call_tool_mock:
            result = executor.execute("change the keyboard lighting to green")

        create_plan_mock.assert_not_called()
        call_tool_mock.assert_called_once()
        self.assertEqual(call_tool_mock.call_args.args[0], "computer_settings")
        self.assertIn("color=green", result)

    def test_direct_route_uses_codex_builder_for_playable_game_requests(self):
        executor = AgentExecutor()

        with patch("agent.executor.create_plan") as create_plan_mock, patch(
            "agent.executor._call_tool",
            return_value="Project directory: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\nOpen target: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\\index.html",
        ) as call_tool_mock:
            result = executor.execute("create a playable snake game website and open it when done")

        create_plan_mock.assert_not_called()
        self.assertEqual(call_tool_mock.call_args.args[0], "codex_builder")
        self.assertIn("Open target:", result)


if __name__ == "__main__":
    unittest.main()
