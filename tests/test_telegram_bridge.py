import unittest
from unittest.mock import Mock, patch

from core import telegram_bridge as tb


class TelegramBridgeTests(unittest.TestCase):
    def test_capability_question_detects_optional_integration_query(self):
        self.assertTrue(tb._looks_like_capability_question("can u access your own browser with lightpanda?"))
        self.assertTrue(tb._looks_like_capability_question("do you have access to tradingagents right now?"))
        self.assertTrue(tb._looks_like_capability_question("do u know how to use the crucix?"))
        self.assertFalse(tb._looks_like_capability_question("use crucix to scan the market"))

    def test_followup_reports_active_task_instead_of_queueing_new_one(self):
        queue = Mock()
        queue.get_status.return_value = {
            "task_id": "abc12345",
            "goal": "build a playable police chase game",
            "status": "running",
            "result": "",
            "error": "",
        }
        message = {
            "text": "open it on my browser",
            "chat": {"id": "42"},
            "message_id": 7,
        }

        with patch.dict(tb._ACTIVE_CHAT_TASKS, {"42": "abc12345"}, clear=True), patch.object(
            tb, "get_queue", return_value=queue
        ), patch.object(tb, "_chat_is_authorized", return_value=True), patch.object(
            tb, "_send_message"
        ) as send_mock, patch.object(tb, "_queue_task") as queue_task_mock:
            tb._handle_message(message)

        queue_task_mock.assert_not_called()
        send_mock.assert_called_once()
        self.assertIn("Active task [abc12345]", send_mock.call_args.args[1])

    def test_plain_message_router_can_queue_task_without_task_prefix(self):
        message = {
            "text": "change the keyboard lighting to green",
            "chat": {"id": "42"},
            "message_id": 7,
        }

        with patch.object(tb, "_chat_is_authorized", return_value=True), patch.object(
            tb, "_chat_can_execute", return_value=True
        ), patch.object(
            tb, "_decide_plain_message_action", return_value={"kind": "task", "goal": "change the keyboard lighting to green", "source": "llm_router"}
        ), patch.object(tb, "_queue_task") as queue_task_mock, patch.object(
            tb, "_send_message"
        ) as send_mock:
            tb._handle_message(message)

        queue_task_mock.assert_called_once()
        send_mock.assert_not_called()

    def test_plain_message_router_keeps_normal_chat_reply(self):
        message = {
            "text": "what's my name?",
            "chat": {"id": "42"},
            "message_id": 8,
        }

        with patch.object(tb, "_chat_is_authorized", return_value=True), patch.object(
            tb, "_chat_can_execute", return_value=True
        ), patch.object(
            tb, "_decide_plain_message_action", return_value={"kind": "chat", "goal": "what's my name?", "source": "llm_router"}
        ), patch.object(tb, "_reply_to_chat") as reply_mock, patch.object(
            tb, "_queue_task"
        ) as queue_task_mock:
            tb._handle_message(message)

        reply_mock.assert_called_once()
        queue_task_mock.assert_not_called()

    def test_contextualize_rgb_followup_rewrites_pronoun_goal(self):
        with patch.dict(
            tb._LAST_CHAT_TASK_RESULTS,
            {
                "42": {
                    "task_id": "rgb1",
                    "goal": "change the keyboard lighting to red",
                    "result": "Hardware RGB updated: ASUS TUF Laptop Keyboard: color=red.",
                }
            },
            clear=True,
        ):
            rewritten = tb._contextualize_task_goal("42", "change it to green")

        self.assertEqual(rewritten, "change the keyboard lighting to green")

    def test_contextualize_rgb_followup_handles_terse_fuzzy_color(self):
        with patch.dict(
            tb._LAST_CHAT_TASK_RESULTS,
            {
                "42": {
                    "task_id": "rgb1",
                    "goal": "change the keyboard lighting to red",
                    "result": "Hardware RGB updated: ASUS TUF Laptop Keyboard: color=red.",
                }
            },
            clear=True,
        ):
            rewritten = tb._contextualize_task_goal("42", "grain")

        self.assertEqual(rewritten, "change the keyboard lighting to green")

    def test_contextualize_open_followup_uses_last_artifact(self):
        with patch.dict(
            tb._LAST_CHAT_TASK_RESULTS,
            {
                "42": {
                    "task_id": "game1",
                    "goal": "create a playable snake game",
                    "result": "Project directory: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\nOpen target: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\\index.html",
                }
            },
            clear=True,
        ):
            rewritten = tb._contextualize_task_goal("42", "open it")

        self.assertEqual(
            rewritten,
            "open this artifact: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\\index.html",
        )

    def test_contextualize_open_followup_uses_persisted_last_artifact(self):
        with patch.dict(tb._LAST_CHAT_TASK_RESULTS, {}, clear=True), patch.object(
            tb,
            "_channel_state",
            return_value={
                "last_task_id": "game1",
                "last_goal": "create a playable snake game",
                "last_result": "Project directory: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\nOpen target: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\\index.html",
            },
        ):
            rewritten = tb._contextualize_task_goal("42", "open it")

        self.assertEqual(
            rewritten,
            "open this artifact: C:\\Users\\moyes\\Desktop\\AXIOMProjects\\snake\\index.html",
        )

    def test_active_task_snapshot_recovers_persisted_active_task(self):
        queue = Mock()
        queue.get_status.return_value = {
            "task_id": "abc12345",
            "goal": "build a playable police chase game",
            "status": "running",
            "result": "",
            "error": "",
        }

        with patch.dict(tb._ACTIVE_CHAT_TASKS, {}, clear=True), patch.object(
            tb,
            "_channel_state",
            return_value={"active_task_id": "abc12345"},
        ), patch.object(tb, "get_queue", return_value=queue):
            status = tb._active_task_snapshot("42")
            self.assertEqual(tb._ACTIVE_CHAT_TASKS["42"], "abc12345")

        self.assertEqual(status["task_id"], "abc12345")

    def test_decide_plain_message_action_falls_back_to_heuristic_when_router_empty(self):
        with patch.object(tb, "_llm_plain_message_decision", return_value={}), patch.object(
            tb, "_plain_message_mode", return_value="smart"
        ):
            decision = tb._decide_plain_message_action("open calculator", chat_id="42")

        self.assertEqual(decision["kind"], "task")
        self.assertEqual(decision["goal"], "open calculator")

    def test_operator_mode_defaults_terse_actionable_message_to_task(self):
        with patch.object(tb, "_llm_plain_message_decision", return_value={"kind": "chat", "goal": "calculator"}), patch.object(
            tb, "_plain_message_mode", return_value="operator"
        ):
            decision = tb._decide_plain_message_action("calculator", chat_id="42")

        self.assertEqual(decision["kind"], "task")
        self.assertEqual(decision["goal"], "calculator")

    def test_operator_mode_keeps_small_talk_as_chat(self):
        with patch.object(tb, "_plain_message_mode", return_value="operator"):
            decision = tb._decide_plain_message_action("how are you", chat_id="42")

        self.assertEqual(decision["kind"], "chat")
        self.assertEqual(decision["goal"], "how are you")

    def test_operator_mode_keeps_crucix_capability_question_as_chat(self):
        with patch.object(tb, "_plain_message_mode", return_value="operator"):
            decision = tb._decide_plain_message_action("Do u know how to use the crucix?", chat_id="42")

        self.assertEqual(decision["kind"], "chat")
        self.assertEqual(decision["source"], "operator_chat_guard")

    def test_operator_mode_keeps_gratitude_as_chat(self):
        with patch.object(tb, "_plain_message_mode", return_value="operator"):
            decision = tb._decide_plain_message_action("smooth thanks", chat_id="42")

        self.assertEqual(decision["kind"], "chat")
        self.assertEqual(decision["goal"], "smooth thanks")

    def test_operator_mode_routes_explicit_tool_instruction_to_task(self):
        with patch.object(tb, "_llm_plain_message_decision", return_value={"kind": "chat", "goal": "use gemini_native status"}), patch.object(
            tb, "_plain_message_mode", return_value="operator"
        ):
            decision = tb._decide_plain_message_action(
                "use gemini_native status and tell me whether live google search is enabled",
                chat_id="42",
            )

        self.assertEqual(decision["kind"], "task")
        self.assertEqual(decision["source"], "operator_explicit_tool")

    def test_render_task_completion_message_drops_robotic_prefix(self):
        message = tb._render_task_completion_message(
            "Hardware RGB updated: ASUS TUF Laptop Keyboard: color=green."
        )

        self.assertEqual(
            message,
            "Hardware RGB updated: ASUS TUF Laptop Keyboard: color=green.",
        )


if __name__ == "__main__":
    unittest.main()
