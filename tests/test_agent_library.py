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

        tradingagents = root / "TradingAgents"
        role_path = tradingagents / "tradingagents" / "agents" / "analysts"
        role_path.mkdir(parents=True, exist_ok=True)
        (role_path / "market_analyst.py").write_text(
            "def run():\n    return 'market'\n",
            encoding="utf-8",
        )
        (tradingagents / "README.md").write_text("TradingAgents README", encoding="utf-8")
        (tradingagents / "pyproject.toml").write_text(
            "[project]\nname='tradingagents'\nversion='0.2.2'\n",
            encoding="utf-8",
        )

        return {
            "wshobson": wshobson,
            "awesome": awesome,
            "dexter": dexter,
            "pentagi": pentagi,
            "tradingagents": tradingagents,
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
                "tradingagents_path": str(repos["tradingagents"]),
            }
        }
        source_specs = {
            "wshobson_agents": {
                "name": "WS Hobson Agents",
                "config_key": "wshobson_agents_path",
                "default_candidates": [],
                "glob": "plugins/*/agents/*.md",
            },
            "awesome_subagents": {
                "name": "Claude Code Subagents",
                "config_key": "awesome_subagents_path",
                "default_candidates": [],
                "glob": "categories/**/*.md",
            },
            "dexter": {
                "name": "Dexter",
                "config_key": "dexter_path",
                "default_candidates": [],
                "special": "dexter",
            },
            "pentagi": {
                "name": "PentAGI",
                "config_key": "pentagi_path",
                "default_candidates": [],
                "special": "pentagi",
            },
            "tradingagents": {
                "name": "TradingAgents",
                "config_key": "tradingagents_path",
                "default_candidates": [],
                "special": "tradingagents",
            },
        }

        with patch.object(al, "load_runtime_config", return_value=runtime), patch.object(
            al, "_SOURCE_SPECS", source_specs
        ):
            status = al.collect_agent_library_status(limit=6)
            entries = al.index_agent_library()
            search = al.search_agent_library("frontend", limit=3)
            recommend = al.recommend_agent_library("design a frontend dashboard", limit=3)

        self.assertTrue(status["enabled"])
        self.assertEqual(status["sources_count"], 5)
        self.assertEqual(status["total_agents"], 5)
        self.assertEqual(len(entries), 5)
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
                "tradingagents_path": str(repos["tradingagents"]),
            }
        }
        source_specs = {
            "wshobson_agents": {
                "name": "WS Hobson Agents",
                "config_key": "wshobson_agents_path",
                "default_candidates": [],
                "glob": "plugins/*/agents/*.md",
            },
            "awesome_subagents": {
                "name": "Claude Code Subagents",
                "config_key": "awesome_subagents_path",
                "default_candidates": [],
                "glob": "categories/**/*.md",
            },
            "dexter": {
                "name": "Dexter",
                "config_key": "dexter_path",
                "default_candidates": [],
                "special": "dexter",
            },
            "pentagi": {
                "name": "PentAGI",
                "config_key": "pentagi_path",
                "default_candidates": [],
                "special": "pentagi",
            },
            "tradingagents": {
                "name": "TradingAgents",
                "config_key": "tradingagents_path",
                "default_candidates": [],
                "special": "tradingagents",
            },
        }

        with patch.object(al, "load_runtime_config", return_value=runtime), patch.object(
            al, "get_gemini_api_key", return_value=""
        ), patch.object(
            al, "_SOURCE_SPECS", source_specs
        ):
            result = al.delegate_agent_library(task="Build a frontend UI", limit=2)

        self.assertFalse(result["ok"])
        self.assertIn("Gemini API key is missing", result["message"])

    def test_indexes_tradingagents_special_roles(self):
        repos = self._make_catalogs()
        runtime = {
            "agent_library": {
                "enabled": True,
                "tradingagents_path": str(repos["tradingagents"]),
            },
            "tradingagents": {
                "repo_path": str(repos["tradingagents"]),
            },
        }
        source_specs = {
            "tradingagents": {
                "name": "TradingAgents",
                "config_key": "tradingagents_path",
                "default_candidates": [],
                "special": "tradingagents",
            }
        }

        with patch.object(al, "load_runtime_config", return_value=runtime), patch.object(
            al, "_SOURCE_SPECS", source_specs
        ):
            entries = al.index_agent_library()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source_id"], "tradingagents")
        self.assertEqual(entries[0]["name"], "Market Analyst")


if __name__ == "__main__":
    unittest.main()
