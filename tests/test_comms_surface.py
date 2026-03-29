import unittest
from unittest.mock import patch

from core import comms_surface as cs


class CommsSurfaceTests(unittest.TestCase):
    def test_collect_status_reports_email_and_telephony_readiness(self):
        runtime = {
            "channels": {"telegram": {"enabled": True, "allowed_chat_ids": ["1"]}},
            "communications": {
                "desktop_apps": {"enabled": True},
                "email": {"enabled": True, "smtp_host": "smtp.example.com", "smtp_port": 587, "from_address": "axiom@example.com"},
                "telephony": {"enabled": True, "provider": "twilio", "from_number": "+15551234567"},
            },
        }

        def fake_secret(name, env_names=None, default=""):
            mapping = {
                "telegram_bot_token": "tg-token",
                "smtp_username": "axiom@example.com",
                "smtp_password": "smtp-secret",
                "smtp_from_address": "axiom@example.com",
                "twilio_account_sid": "sid",
                "twilio_auth_token": "token",
                "twilio_from_number": "+15551234567",
            }
            return mapping.get(name, default)

        with patch.object(cs, "load_runtime_config", return_value=runtime), patch.object(
            cs, "get_secret", side_effect=fake_secret
        ), patch.object(cs, "_has_module", side_effect=lambda name: True):
            status = cs.collect_comms_status()

        self.assertTrue(status["telegram_bridge_enabled"])
        self.assertTrue(status["desktop_messaging_ready"])
        self.assertTrue(status["email"]["ready"])
        self.assertTrue(status["telephony"]["sms_ready"])
        self.assertTrue(status["telephony"]["call_ready"])


if __name__ == "__main__":
    unittest.main()
