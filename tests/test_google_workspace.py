import unittest
from unittest.mock import patch

from core import google_workspace as gw


class GoogleWorkspaceTests(unittest.TestCase):
    def test_collect_status_reflects_runtime_and_library_state(self):
        runtime = {
            "communications": {
                "google_workspace": {
                    "enabled": True,
                    "gmail_enabled": True,
                    "calendar_enabled": True,
                    "client_secret_path": "C:\\Users\\moyes\\client_secret.json",
                    "token_path": "C:\\Users\\moyes\\token.json",
                    "timezone": "America/Regina",
                    "default_calendar_id": "primary",
                }
            },
            "text_models": {
                "default": "gemini-2.5-flash",
                "fast": "gemini-2.5-flash-lite-preview-06-17",
            },
        }

        with patch.object(gw, "load_runtime_config", return_value=runtime), patch.object(
            gw, "_has_module", return_value=True
        ), patch.object(gw.Path, "exists", return_value=True):
            status = gw.collect_google_workspace_status()

        self.assertTrue(status["enabled"])
        self.assertTrue(status["gmail_enabled"])
        self.assertTrue(status["calendar_enabled"])
        self.assertTrue(status["ready"])


if __name__ == "__main__":
    unittest.main()
