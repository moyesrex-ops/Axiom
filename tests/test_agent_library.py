import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from core import agent_library as al


class AgentLibraryTests(unittest.TestCase):
    def setUp(self):
        al._INDEX_CACHE["signature"] = None
        al._INDEX_CACHE["entries"] = []

    def _workspace_dir(self, name: str) -> Path:
        root = Path(__file__).resolve().parent / "_tmp"
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def _make_catalogs(self) -> dict:
        root = self._workspace_dir("agent_library")

        wshobson = root / "wshobson"
        frontend = wshobson / "plugins" / "frontend" / "agents"
        frontend.mkdir(parents=True)
        (frontend / "frontend-developer.md").write_text(
            "---\nname: Frontend Developer\ndescription: Builds interface systems\nmodel: inherit\n---\nReact and UI work.\n",
            encoding="utf-8",
        )

        awesome = root / "awesome"
        backend = awesome / "categories" / "01-core-development"
        backend.mkdir(parents=True)
        (backend / "backend-developer.md").write_text(
            "---\nname: Backend Developer\ndescription: Builds APIs and services\nmodel: sonnet\n---\nBackend systems.\n",
            encoding="utf-8",
        )

        dexter = root / "dexter"
        dexter.mkdir(parents=True)
        (dexter / "README.md").write_text("Dexter README", encoding="utf-8")
        (dexter / "AGENTS.md").write_text("Dexter agent guide", encoding="utf-8")

        pentagi = root / "pentagi"
        pentagi.mkdir(parents=True)
        (pentagi / "README.md").write_text(
            "License compliance audit in progress.\nPentAGI security agent.",
            encoding="utf-8",
        )

        return {
            "wshobson": wshobson,
            "awesome": awesome,
            "dexter": dexter,
            "pentagi": pentagi,
        }

    def test_indexes_catalog_and_special_sources(self):
        repos = self._make_catalogs()
        runtime = {
            "agent_library": {
                "enabled": True,
                "wshobson_agents_path": str(repos["wshobson"]),
                "awesome_subagents_path": str(repos["awesome"]),
                "dexter_path": str(repos["dexter"]),
                "pentagi_path": str(repos["pentagi"]),
            }
        }

        with patch.object(al, "load_runtime_config", return_value=runtime):
            status = al.collect_agent_library_status(limit=6)
            entries = al.index_agent_library()
            search = al.search_agent_library("frontend", limit=3)
            recommend = al.recommend_agent_library("design a frontend dashboard", limit=3)

        self.assertTrue(status["enabled"])
        self.assertEqual(status["sources_count"], 4)
        self.assertEqual(status["total_agents"], 4)
        self.assertEqual(len(entries), 4)
        self.assertEqual(search[0]["name"], "Frontend Developer")
        self.assertEqual(recommend[0]["name"], "Frontend Developer")

    def test_delegate_without_api_key_returns_clean_error(self):
        repos = self._make_catalogs()
        runtime = {
            "agent_library": {
                "enabled": True,
                "wshobson_agents_path": str(repos["wshobson"]),
                "awesome_subagents_path": str(repos["awesome"]),
                "dexter_path": str(repos["dexter"]),
                "pentagi_path": str(repos["pentagi"]),
            }
        }

        with patch.object(al, "load_runtime_config", return_value=runtime), patch.object(
            al, "get_secret", return_value=""
        ):
            result = al.delegate_agent_library(task="Build a frontend UI", limit=2)

        self.assertFalse(result["ok"])
        self.assertIn("Gemini API key is missing", result["message"])


if __name__ == "__main__":
    unittest.main()
