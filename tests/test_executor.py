import io
import sys
import unittest
from unittest.mock import patch

from agent.executor import AgentExecutor, _direct_tool_for_goal, _safe_print as executor_safe_print, _specialist_context
from agent.completion_verifier import CompletionReport
from agent.error_handler import ErrorDecision


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

    def test_safe_print_handles_cp1252_streams(self):
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="cp1252")
        original_stdout = sys.stdout
        try:
            sys.stdout = stdout
            executor_safe_print("[Executor] unicode fallback \U0001f680")
            stdout.flush()
        finally:
            sys.stdout = original_stdout

        rendered = buffer.getvalue().decode("cp1252")
        self.assertIn("[Executor] unicode fallback", rendered)

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
        ), patch("agent.executor._call_tool", return_value="done"), patch(
            "agent.executor.verify_goal_completion",
            return_value=CompletionReport(
                goal="build a frontend dashboard",
                is_complete=True,
                confidence=0.9,
                summary="Verification passed.",
            ),
        ), patch("agent.executor.extract_and_save_lessons"):
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

    def test_specialist_context_includes_skill_preview_guidance(self):
        with patch("agent.executor.search_knowledge_items", return_value=[]), patch(
            "agent.executor._should_prepare_specialists",
            return_value=True,
        ), patch(
            "core.skill_library.recommend_skill_library",
            return_value=[
                {
                    "id": "planning_with_files:planning-with-files",
                    "name": "planning-with-files",
                    "description": "Persistent file-backed planning workflow.",
                    "content_preview": "Create task_plan.md, findings.md, and progress.md to keep multi-step work grounded.",
                }
            ],
        ), patch("core.agent_library.recommend_agent_library", return_value=[]):
            context = _specialist_context("plan a complex implementation")

        self.assertIn("[RECOMMENDED SKILLS]", context)
        self.assertIn("Guidance: Create task_plan.md", context)

    def test_market_goal_is_not_misrouted_to_codex_builder(self):
        goal = (
            "continuous deep analysis of forex markets with appropriate parameters, "
            "then place MT5 trades based on the research"
        )

        direct = _direct_tool_for_goal(goal)

        self.assertNotEqual(direct[0] if direct else None, "codex_builder")

    def test_executor_retry_recovery_path_no_longer_references_undefined_state(self):
        executor = AgentExecutor()
        fake_plan = {
            "goal": "research dashboard competitors",
            "steps": [
                {
                    "step": 1,
                    "tool": "web_search",
                    "description": "Research dashboard competitors",
                    "parameters": {"query": "dashboard competitors"},
                    "critical": True,
                }
            ],
        }
        call_results = [RuntimeError("temporary network issue"), "Search results for: dashboard competitors"]

        def _fake_call(*args, **kwargs):
            result = call_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        with patch("agent.executor._direct_tool_for_goal", return_value=None), patch(
            "agent.executor._specialist_context", return_value=""
        ), patch("agent.executor.create_plan", return_value=fake_plan), patch(
            "agent.executor.reflect_and_improve", return_value=fake_plan
        ), patch("agent.executor._call_tool", side_effect=_fake_call), patch(
            "agent.executor.analyze_error",
            return_value={
                "decision": ErrorDecision.RETRY,
                "reason": "Transient network issue",
                "fix_suggestion": "",
                "user_message": "Retrying.",
            },
        ), patch(
            "agent.executor.verify_goal_completion",
            return_value=CompletionReport(
                goal="research dashboard competitors",
                is_complete=True,
                confidence=0.91,
                summary="Verification passed.",
            ),
        ), patch("agent.executor.extract_and_save_lessons"), patch(
            "agent.executor.append_task_event"
        ) as append_event_mock, patch(
            "agent.executor.upsert_task_step"
        ) as upsert_step_mock:
            result = executor.execute(
                "research dashboard competitors",
                task_id="abc123",
                task_metadata={"channel": "telegram"},
            )

        self.assertIn("Search results for", result)
        self.assertTrue(append_event_mock.called)
        self.assertTrue(upsert_step_mock.called)


if __name__ == "__main__":
    unittest.main()
