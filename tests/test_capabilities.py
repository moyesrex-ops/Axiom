import unittest
from unittest.mock import patch

from core.capabilities import format_operator_surface


class CapabilitySurfaceTests(unittest.TestCase):
    def test_operator_surface_calls_out_terminal_and_specialist_catalogs(self):
        with patch(
            "core.capabilities.collect_capabilities",
            return_value={
                "telegram_bridge_enabled": True,
                "telegram_bot_configured": True,
                "telegram_allowed_chat_count": 1,
                "deerflow_repo_path": "C:\\DeerFlow",
                "deerflow_proxy_reachable": True,
                "lightpanda_repo_path": "C:\\Lightpanda",
                "lightpanda_reachable": False,
            },
        ), patch(
            "core.capabilities.collect_skill_library_status",
            return_value={
                "enabled": True,
                "sources_count": 2,
                "total_skills": 14,
                "sources": [{"name": "planning-with-files"}, {"name": "last30days-skill"}],
            },
        ), patch(
            "core.capabilities.collect_agent_library_status",
            return_value={
                "enabled": True,
                "sources_count": 2,
                "total_agents": 9,
                "sources": [{"name": "OpenManus"}, {"name": "TradingAgents"}],
            },
        ):
            report = format_operator_surface(limit=2)

        self.assertIn("[OPERATOR SURFACE]", report)
        self.assertIn("cmd_control", report)
        self.assertIn("planning-with-files", report)
        self.assertIn("OpenManus", report)
        self.assertIn("Telegram is live", report)


if __name__ == "__main__":
    unittest.main()
