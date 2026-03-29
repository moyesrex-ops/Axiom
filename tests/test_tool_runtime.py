import unittest
from unittest.mock import patch

from core.tool_runtime import execute_tool


class ToolRuntimeTests(unittest.TestCase):
    def test_execute_tool_records_trace_metadata(self):
        with patch("core.tool_runtime._resolve_callable", return_value=(lambda parameters, speak=None: "ok", "Done.")), patch(
            "core.tool_runtime.record_tool_trace"
        ) as record_trace, patch("core.tool_runtime.log_event"), patch("core.tool_runtime.log_failure"):
            result = execute_tool(
                "mock_tool",
                {"hello": "world"},
                speak=None,
                channel="task",
                source="unit_test",
                metadata={"goal": "demo"},
            )

        self.assertEqual(result, "ok")
        self.assertTrue(record_trace.called)
        self.assertEqual(record_trace.call_args.kwargs["tool"], "mock_tool")
        self.assertEqual(record_trace.call_args.kwargs["channel"], "task")
        self.assertEqual(record_trace.call_args.kwargs["source"], "unit_test")
        self.assertEqual(record_trace.call_args.kwargs["metadata"]["goal"], "demo")

    def test_screen_process_alias_maps_angle_to_source(self):
        captured = {}

        def _fake_tool(parameters, speak=None):
            captured.update(parameters)
            return "done"

        with patch("core.tool_runtime._resolve_callable", return_value=(_fake_tool, "Done.")), patch(
            "core.tool_runtime.record_tool_trace"
        ), patch("core.tool_runtime.log_event"), patch("core.tool_runtime.log_failure"):
            execute_tool("screen_process", {"angle": "camera", "text": "what do you see?"})

        self.assertEqual(captured["action"], "analyze")
        self.assertEqual(captured["source"], "camera")


if __name__ == "__main__":
    unittest.main()
