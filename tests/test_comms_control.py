import unittest
from unittest.mock import patch

from actions import comms_control as cc


class CommsControlTests(unittest.TestCase):
    def test_gmail_recent_formats_messages(self):
        with patch.object(
            cc,
            "gmail_list_recent_messages",
            return_value={
                "count": 1,
                "messages": [
                    {
                        "id": "abc123",
                        "label_ids": ["UNREAD"],
                        "from": "sender@example.com",
                        "subject": "Hello",
                        "date": "Mon, 31 Mar 2026 10:00:00 -0600",
                    }
                ],
            },
        ), patch.object(cc, "log_event"):
            report = cc.comms_control({"action": "gmail_recent", "count": 1})

        self.assertIn("[GMAIL] 1 message(s)", report)
        self.assertIn("abc123", report)
        self.assertIn("UNREAD", report)

    def test_gmail_reply_draft_uses_generated_reply_when_body_missing(self):
        with patch.object(cc, "_resolve_message_id", return_value="abc123"), patch.object(
            cc, "gmail_read_message", return_value={"id": "abc123", "subject": "Hello"}
        ), patch.object(
            cc, "gmail_generate_reply", return_value="Thanks, that works for me."
        ) as generate_mock, patch.object(
            cc,
            "gmail_reply_to_message",
            return_value={"mode": "draft", "to": "sender@example.com", "subject": "Re: Hello"},
        ) as reply_mock, patch.object(
            cc, "save_to_nexus"
        ), patch.object(
            cc, "log_event"
        ):
            report = cc.comms_control({"action": "gmail_reply_draft"})

        generate_mock.assert_called_once()
        reply_mock.assert_called_once()
        self.assertIn("Gmail reply draft", report)

    def test_calendar_book_can_use_natural_language_request(self):
        with patch.object(
            cc,
            "plan_calendar_event_from_text",
            return_value={
                "summary": "Dentist appointment",
                "start_iso": "2026-04-02T15:00:00-06:00",
                "end_iso": "2026-04-02T15:30:00-06:00",
                "description": "Quarterly cleaning",
                "location": "Downtown Clinic",
                "attendees": ["office@example.com"],
            },
        ) as plan_mock, patch.object(
            cc,
            "calendar_create_event",
            return_value={
                "summary": "Dentist appointment",
                "start": "2026-04-02T15:00:00-06:00",
                "end": "2026-04-02T15:30:00-06:00",
            },
        ) as create_mock, patch.object(
            cc, "save_to_nexus"
        ), patch.object(
            cc, "log_event"
        ):
            report = cc.comms_control(
                {
                    "action": "calendar_book",
                    "when": "Book a dentist appointment for Thursday at 3pm for 30 minutes",
                }
            )

        plan_mock.assert_called_once()
        create_mock.assert_called_once()
        self.assertIn("Calendar event booked", report)


if __name__ == "__main__":
    unittest.main()
