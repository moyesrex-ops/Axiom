import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from core import skill_library as sk


class SkillLibraryTests(unittest.TestCase):
    def setUp(self):
        sk._INDEX_CACHE["signature"] = None
        sk._INDEX_CACHE["entries"] = []

    def _workspace_dir(self, name: str) -> Path:
        root = Path(__file__).resolve().parent / "_tmp"
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def _make_repo(self) -> Path:
        repo_path = self._workspace_dir("skill_library_repo")
        skill_dir = repo_path / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Demo Skill\ndescription: First version\n---\nBody\n",
            encoding="utf-8",
        )
        (skill_dir / "README.md").write_text("Demo readme", encoding="utf-8")
        return repo_path

    def _source_specs(self) -> dict:
        return {
            "everything_claude_code": {
                "name": "Everything Claude Code",
                "config_key": "everything_claude_code_path",
                "default_candidates": [],
            }
        }

    def test_indexes_local_skills_root_without_nested_skills_folder(self):
        repo_path = self._workspace_dir("local_skills_repo")
        skill_dir = repo_path / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Local Skill\ndescription: Local root skill\n---\nBody\n",
            encoding="utf-8",
        )
        runtime = {
            "skill_library": {
                "enabled": True,
                "local_skills_path": str(repo_path),
            }
        }
        source_specs = {
            "local_skills": {
                "name": "Local Skills",
                "config_key": "local_skills_path",
                "default_candidates": [],
                "skills_subdir": ".",
            }
        }

        with patch.object(sk, "load_runtime_config", return_value=runtime), patch.object(
            sk, "_SOURCE_SPECS", source_specs
        ):
            entries = sk.index_skill_library()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "Local Skill")

    def test_disabled_library_reports_sources_but_indexes_nothing(self):
        repo_path = self._make_repo()
        runtime = {
            "skill_library": {
                "enabled": False,
                "everything_claude_code_path": str(repo_path),
            }
        }
        with patch.object(sk, "load_runtime_config", return_value=runtime), patch.object(
            sk, "_SOURCE_SPECS", self._source_specs()
        ):
            status = sk.collect_skill_library_status(limit=3)
            entries = sk.index_skill_library()

        self.assertFalse(status["enabled"])
        self.assertEqual(status["sources_count"], 1)
        self.assertEqual(status["total_skills"], 0)
        self.assertEqual(entries, [])

    def test_signature_tracks_nested_skill_changes(self):
        repo_path = self._make_repo()
        skill_path = repo_path / "skills" / "demo-skill" / "SKILL.md"
        runtime = {
            "skill_library": {
                "enabled": True,
                "everything_claude_code_path": str(repo_path),
            }
        }

        with patch.object(sk, "load_runtime_config", return_value=runtime), patch.object(
            sk, "_SOURCE_SPECS", self._source_specs()
        ):
            first = sk.index_skill_library()
            self.assertEqual(first[0]["description"], "First version")

            skill_path.write_text(
                "---\nname: Demo Skill\ndescription: Updated version\n---\nBody\n",
                encoding="utf-8",
            )
            second = sk.index_skill_library()

        self.assertEqual(second[0]["description"], "Updated version")


if __name__ == "__main__":
    unittest.main()
