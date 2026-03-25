import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import shutil

from actions import codex_builder as cb


class CodexBuilderTests(unittest.TestCase):
    def test_build_parses_result_block(self):
        completed = Mock(returncode=0, stdout="AXIOM_RESULT\nproject_dir: C:\\tmp\\snake\nentry_path: C:\\tmp\\snake\\index.html\nopen_target: C:\\tmp\\snake\\index.html\nrun_command: none\nsummary: playable snake game ready\nEND_AXIOM_RESULT\n", stderr="")

        tmpdir = Path(__file__).resolve().parent / "_tmp" / "codex_builder"
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            project_dir = tmpdir / "snake"
            with patch.object(cb, "_codex_binary", return_value="codex.cmd"), patch.object(
                cb, "_projects_dir", return_value=tmpdir
            ), patch.object(
                cb, "_open_target", return_value=""
            ), patch.object(
                cb.subprocess, "run", return_value=completed
            ), patch.object(
                cb, "save_to_memory_archive"
            ), patch.object(
                cb, "log_event"
            ):
                result = cb.codex_builder(
                    {
                        "action": "build",
                        "description": "create a playable snake game",
                        "project_name": "snake",
                    }
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertIn("Project directory:", result)
        self.assertIn("Entry file: C:\\tmp\\snake\\index.html", result)
        self.assertIn("Summary: playable snake game ready", result)

    def test_status_reports_missing_or_present_binary(self):
        with patch.object(cb, "_codex_binary", return_value="C:\\tools\\codex.cmd"), patch.object(
            cb, "_projects_dir", return_value=Path("C:/Projects")
        ):
            result = cb.codex_builder({"action": "status"})

        self.assertIn("Codex binary: C:\\tools\\codex.cmd", result)
        self.assertIn("Projects dir: C:\\Projects", result)


if __name__ == "__main__":
    unittest.main()
