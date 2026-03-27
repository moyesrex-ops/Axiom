import unittest
from pathlib import Path
from unittest.mock import patch

from actions import cmd_control as cc


class CmdControlTests(unittest.TestCase):
    def test_exact_powershell_command_runs_in_repo_cwd(self):
        with patch.object(cc, "_run_silent", return_value="ok") as run_mock, patch.object(
            cc, "log_event"
        ):
            result = cc.cmd_control(
                {
                    "command": "Get-Location",
                    "shell": "powershell",
                    "cwd": "repo",
                    "visible": False,
                }
            )

        self.assertEqual(result, "ok")
        self.assertEqual(run_mock.call_args.kwargs["shell"], "powershell")
        self.assertEqual(run_mock.call_args.kwargs["cwd"], cc.BASE_DIR)

    def test_vscode_terminal_mode_uses_integrated_terminal_helper(self):
        with patch.object(
            cc,
            "_run_vscode_terminal",
            return_value="VS Code workspace opened.",
        ) as vscode_mock, patch.object(cc, "log_event"):
            result = cc.cmd_control(
                {
                    "command": "codex --help",
                    "shell": "powershell",
                    "cwd": "repo",
                    "open_in_vscode": True,
                }
            )

        self.assertEqual(result, "VS Code workspace opened.")
        self.assertEqual(vscode_mock.call_args.args[2], cc.BASE_DIR)

    def test_dangerous_command_is_blocked(self):
        with patch.object(cc, "log_event"):
            result = cc.cmd_control(
                {
                    "command": "git reset --hard",
                    "shell": "powershell",
                    "visible": False,
                }
            )

        self.assertIn("Blocked for safety", result)

    def test_safe_powershell_format_flag_is_not_blocked(self):
        with patch.object(cc, "_run_silent", return_value="2026-03-26T12:00:00.0000000-06:00") as run_mock, patch.object(
            cc, "log_event"
        ):
            result = cc.cmd_control(
                {
                    "command": "Get-Date -Format o",
                    "shell": "powershell",
                    "visible": False,
                }
            )

        self.assertEqual(result, "2026-03-26T12:00:00.0000000-06:00")
        self.assertEqual(run_mock.call_args.kwargs["shell"], "powershell")

    def test_disk_format_command_stays_blocked(self):
        with patch.object(cc, "log_event"):
            result = cc.cmd_control(
                {
                    "command": "format D:",
                    "shell": "cmd",
                    "visible": False,
                }
            )

        self.assertIn("Blocked for safety", result)

    def test_repo_shortcut_resolves_to_repo_base(self):
        resolved = cc._resolve_workdir("repo", task="", command="")
        self.assertEqual(resolved, Path(cc.BASE_DIR))


if __name__ == "__main__":
    unittest.main()
