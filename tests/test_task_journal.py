import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent.task_queue import TaskPriority
from core.task_channels import submit_channel_task
from core.task_journal import format_task_snapshot
from memory import runtime_store as rs


class TaskJournalTests(unittest.TestCase):
    def test_runtime_store_records_task_events_and_steps(self):
        tmpdir = Path(__file__).resolve().parent / "_tmp" / "task_journal_1"
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            db_path = tmpdir / "axiom_state.db"
            with patch.object(rs, "DB_PATH", db_path):
                rs._INITIALIZED = False
                rs.init_runtime_store()
                rs.upsert_task_run(
                    "abc123",
                    "build a dashboard",
                    "running",
                    metadata={"phase": "executing", "plan_revision": 1, "channel": "telegram"},
                )
                rs.append_task_event(
                    "abc123",
                    "plan_created",
                    "Initial plan created.",
                    phase="planning",
                    metadata={"plan_revision": 1},
                )
                rs.upsert_task_step(
                    "abc123",
                    1,
                    revision=1,
                    tool="web_search",
                    description="Research similar dashboards",
                    status="completed",
                    parameters={"query": "dashboard inspiration"},
                    result_text="Search results for: dashboard inspiration",
                )
                rs.upsert_task_step(
                    "abc123",
                    2,
                    revision=1,
                    tool="codex_builder",
                    description="Build the dashboard",
                    status="running",
                    parameters={"action": "build"},
                )

                task = rs.get_task_run("abc123")
                steps = rs.list_task_steps("abc123", revision=1)
                events = rs.recent_task_events(task_id="abc123", limit=3)
                summary = format_task_snapshot("abc123")
                rs._INITIALIZED = False
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertEqual(task["metadata"]["phase"], "executing")
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["tool"], "web_search")
        self.assertEqual(events[0]["topic"], "plan_created")
        self.assertIn("Active task", summary.replace("Task [", "Active task [", 1))
        self.assertIn("Phase: executing", summary)
        self.assertIn("Progress: 1/2", summary)
        self.assertIn("Current step: #2 [codex_builder]", summary)

    def test_submit_channel_task_uses_shared_channel_metadata(self):
        queue = Mock()
        queue.submit.return_value = "abc123"

        with patch("core.task_channels.get_queue", return_value=queue):
            task_id = submit_channel_task(
                "build a dashboard",
                channel="telegram",
                scope="42",
                origin="telegram_bridge",
                priority=TaskPriority.HIGH,
            )

        self.assertEqual(task_id, "abc123")
        kwargs = queue.submit.call_args.kwargs
        self.assertEqual(kwargs["goal"], "build a dashboard")
        self.assertEqual(kwargs["priority"], TaskPriority.HIGH)
        self.assertEqual(kwargs["metadata"]["channel"], "telegram")
        self.assertEqual(kwargs["metadata"]["scope"], "42")
        self.assertEqual(kwargs["metadata"]["origin"], "telegram_bridge")


if __name__ == "__main__":
    unittest.main()
