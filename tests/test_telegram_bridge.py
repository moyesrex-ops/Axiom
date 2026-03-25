import unittest
from unittest.mock import Mock, patch

from core import telegram_bridge as tb


class TelegramBridgeTests(unittest.TestCase):
    def test_capability_question_detects_optional_integration_query(self):
        self.assertTrue(tb._looks_like_capability_question("can u access your own browser with lightpanda?"))
        self.assertTrue(tb._looks_like_capability_question("do you have access to tradingagents right now?"))

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


if __name__ == "__main__":
    unittest.main()
