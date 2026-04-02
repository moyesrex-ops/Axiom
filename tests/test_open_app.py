import unittest

from actions import open_app as open_app_module


class OpenAppTests(unittest.TestCase):
    def test_mail_process_tokens_include_windows_mail_hints(self):
        tokens = set(open_app_module._process_tokens("mail", "Mail"))

        self.assertIn("mail", tokens)
        self.assertIn("hxmail", tokens)
        self.assertIn("outlook", tokens)

    def test_mail_title_tokens_include_inbox_and_outlook_hints(self):
        tokens = set(open_app_module._title_tokens("mail", "Mail"))

        self.assertIn("mail", tokens)
        self.assertIn("inbox", tokens)
        self.assertIn("outlook", tokens)

    def test_windows_launch_memory_round_trip(self):
        open_app_module._LAST_WINDOWS_LAUNCHES.clear()

        open_app_module._remember_windows_launch(
            "Mail",
            "Mail",
            started_via="startapps",
            start_app_name="Outlook (new)",
            start_app_id="Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows",
        )

        remembered = open_app_module._lookup_windows_launch("mail", "Mail")
        self.assertEqual(remembered["started_via"], "startapps")
        self.assertEqual(remembered["start_app_name"], "Outlook (new)")
        self.assertIn("outlook", remembered["title_tokens"])


if __name__ == "__main__":
    unittest.main()
