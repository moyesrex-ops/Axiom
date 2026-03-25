import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from core import tradingagents_bridge as tb


class TradingAgentsBridgeTests(unittest.TestCase):
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
        repo = self._workspace_dir("tradingagents_repo")
        (repo / "README.md").write_text("TradingAgents README", encoding="utf-8")
        (repo / "pyproject.toml").write_text(
            """
[project]
name = "tradingagents"
version = "0.2.2"
""".strip(),
            encoding="utf-8",
        )
        role_path = repo / "tradingagents" / "agents" / "analysts"
        role_path.mkdir(parents=True, exist_ok=True)
        (role_path / "market_analyst.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
        (repo / "tradingagents" / "graph").mkdir(parents=True, exist_ok=True)
        (repo / "tradingagents" / "graph" / "trading_graph.py").write_text("class TradingAgentsGraph: pass\n", encoding="utf-8")
        venv_python = repo / ".venv" / "Scripts"
        venv_python.mkdir(parents=True, exist_ok=True)
        (venv_python / "python.exe").write_text("", encoding="utf-8")
        return repo

    def test_collect_status_reports_prepared_repo(self):
        repo = self._make_repo()
        runtime = {
            "tradingagents": {
                "repo_path": str(repo),
                "provider": "google",
            }
        }

        with patch.object(tb, "load_runtime_config", return_value=runtime), patch.object(
            tb, "_venv_import_ready", return_value=(True, "ready")
        ):
            status = tb.collect_tradingagents_status(limit=3)

        self.assertEqual(status["repo_path"], str(repo))
        self.assertTrue(status["venv_ready"])
        self.assertTrue(status["import_ready"])
        self.assertEqual(status["role_count"], 1)
        self.assertEqual(status["provider"], "google")


if __name__ == "__main__":
    unittest.main()
