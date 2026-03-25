import unittest
from unittest.mock import patch

from agent.executor import AgentExecutor, _specialist_context


class ExecutorDirectRouteTests(unittest.TestCase):
    def test_direct_route_handles_rgb_goal_without_planner(self):
        executor = AgentExecutor()

        with patch("agent.executor._specialist_context", return_value=""), patch(
            "agent.executor.create_plan"
        ) as create_plan_mock, patch(
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

        with patch("agent.executor._specialist_context", return_value=""), patch(
            "agent.executor.create_plan"
        ) as create_plan_mock, patch(
            "agent.executor._call_tool",
            return_value="Project directory: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\nOpen target: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\\index.html",
        ) as call_tool_mock:
            result = executor.execute("create a playable snake game website and open it when done")

        create_plan_mock.assert_not_called()
        self.assertEqual(call_tool_mock.call_args.args[0], "codex_builder")
        self.assertIn("Open target:", result)

    def test_planner_receives_specialist_context_for_complex_tasks(self):
        executor = AgentExecutor()
        fake_plan = {
            "goal": "build a frontend dashboard",
            "steps": [
                {
                    "step": 1,
                    "tool": "web_search",
                    "description": "research",
                    "parameters": {"query": "frontend dashboard"},
                    "critical": True,
                }
            ],
        }

        with patch("agent.executor._direct_tool_for_goal", return_value=None), patch(
            "agent.executor._specialist_context", return_value="[SPECIALIST PREFLIGHT]\nUse frontend reviewer."
        ), patch("agent.executor.create_plan", return_value=fake_plan) as create_plan_mock, patch(
            "agent.executor.reflect_and_improve", return_value=fake_plan
        ), patch("agent.executor._call_tool", return_value="done"):
            executor.execute("build a frontend dashboard")

        self.assertEqual(
            create_plan_mock.call_args.kwargs["context"],
            "[SPECIALIST PREFLIGHT]\nUse frontend reviewer.",
        )

    def test_direct_route_fuzzy_matches_rgb_followup_color(self):
        executor = AgentExecutor()

        with patch("agent.executor._specialist_context", return_value=""), patch(
            "agent.executor.create_plan"
        ) as create_plan_mock, patch(
            "agent.executor._call_tool",
            return_value="Hardware RGB updated: ASUS TUF Laptop Keyboard: color=green.",
        ) as call_tool_mock:
            result = executor.execute("change the keyboard lighting to grain")

        create_plan_mock.assert_not_called()
        self.assertEqual(call_tool_mock.call_args.args[0], "computer_settings")
        self.assertEqual(call_tool_mock.call_args.args[1]["value"], "green")
        self.assertIn("color=green", result)

    def test_specialist_context_includes_learned_task_strategy(self):
        with patch(
            "agent.executor.search_knowledge_items",
            return_value=[
                {
                    "title": "Task Strategy: Build dashboard",
                    "content": "Goal: build a dashboard. Steps: use codex_builder after frontend skill preflight.",
                }
            ],
        ), patch("core.skill_library.recommend_skill_library", side_effect=Exception("skip")), patch(
            "core.agent_library.recommend_agent_library", side_effect=Exception("skip")
        ):
            context = _specialist_context("build a dashboard")

        self.assertIn("[LEARNED STRATEGIES]", context)
        self.assertIn("Task Strategy: Build dashboard", context)


if __name__ == "__main__":
    unittest.main()
