import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from core import deerflow_bridge as df


class _FakeResponse:
    def __init__(self, payload=None, lines=None):
        self._payload = payload or {}
        self._lines = list(lines or [])

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        for line in self._lines:
            yield line

    def close(self):
        return None


class DeerFlowBridgeTests(unittest.TestCase):
    def _workspace_dir(self, name: str) -> Path:
        root = Path(__file__).resolve().parent / "_tmp"
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_collect_status_detects_local_repo_and_skills(self):
        repo = self._workspace_dir("deerflow_repo")
        (repo / "backend").mkdir(parents=True)
        (repo / "skills" / "public" / "demo").mkdir(parents=True)
        (repo / "README.md").write_text("DeerFlow", encoding="utf-8")
        (repo / "backend" / "pyproject.toml").write_text("[project]\nname='deerflow'\n", encoding="utf-8")
        (repo / "skills" / "public" / "demo" / "SKILL.md").write_text("demo", encoding="utf-8")

        runtime = {"deerflow": {"repo_path": str(repo), "url": "http://127.0.0.1:2026"}}
        with patch.object(df, "load_runtime_config", return_value=runtime), patch.object(
            df, "_safe_json_get", return_value=(False, {})
        ):
            status = df.collect_deerflow_status(limit=3)

        self.assertEqual(status["repo_path"], str(repo))
        self.assertFalse(status["proxy_reachable"])
        self.assertEqual(status["local_skill_count"], 1)

    def test_run_query_parses_values_stream(self):
        status = {
            "repo_path": "C:\\Users\\moyes\\deer-flow_upstream",
            "gateway_url": "http://127.0.0.1:2026",
            "langgraph_url": "http://127.0.0.1:2026/api/langgraph",
            "proxy_reachable": True,
        }
        stream_lines = [
            "event: metadata",
            'data: {"run_id":"run-1"}',
            "",
            "event: values",
            'data: {"messages":[{"type":"human","content":[{"type":"text","text":"hi"}]},{"type":"ai","content":[{"type":"text","text":"done"}]}]}',
            "",
        ]

        with patch.object(df, "collect_deerflow_status", return_value=status), patch.object(
            df.requests,
            "post",
            side_effect=[
                _FakeResponse(payload={"thread_id": "thread-1"}),
                _FakeResponse(lines=stream_lines),
            ],
        ):
            result = df.run_deerflow_query("hello", mode="pro")

        self.assertTrue(result["ok"])
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(result["run_id"], "run-1")
        self.assertEqual(result["response_text"], "done")


if __name__ == "__main__":
    unittest.main()
