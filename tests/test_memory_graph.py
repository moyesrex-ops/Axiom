import unittest
from pathlib import Path
from unittest.mock import patch
import shutil

from memory import memory_manager as mm
from memory import runtime_store as rs


class MemoryGraphTests(unittest.TestCase):
    def test_conversation_turn_indexes_graph_facts(self):
        tmpdir = Path(__file__).resolve().parent / "_tmp" / "memory_graph_1"
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            db_path = tmpdir / "axiom_state.db"
            with patch.object(rs, "DB_PATH", db_path), patch.object(mm, "MEMORY_PATH", tmpdir / "long_term.json"):
                rs._INITIALIZED = False
                rs.init_runtime_store()
                rs.log_conversation_turn("my name is cameron and i live in regina", "Noted.")

                rows = rs.search_graph_memory("regina", limit=5)
                rs._INITIALIZED = False
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertTrue(any(row["target_name"] == "Regina" for row in rows))

    def test_search_memory_archive_returns_graph_hits(self):
        tmpdir = Path(__file__).resolve().parent / "_tmp" / "memory_graph_2"
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            db_path = tmpdir / "axiom_state.db"
            memory_path = tmpdir / "long_term.json"
            with patch.object(rs, "DB_PATH", db_path), patch.object(mm, "MEMORY_PATH", memory_path):
                rs._INITIALIZED = False
                rs.init_runtime_store()
                rs.log_conversation_turn("call me master", "Understood.")

                hits = mm.search_memory_archive("master", limit=3)
                rs._INITIALIZED = False
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertIn("graph", hits)
        self.assertTrue(any(row["target_name"] == "Master" for row in hits["graph"]))

    def test_channel_turns_update_durable_channel_state(self):
        tmpdir = Path(__file__).resolve().parent / "_tmp" / "memory_graph_3"
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            db_path = tmpdir / "axiom_state.db"
            with patch.object(rs, "DB_PATH", db_path), patch.object(mm, "MEMORY_PATH", tmpdir / "long_term.json"):
                rs._INITIALIZED = False
                rs.init_runtime_store()
                rs.log_conversation_turn(
                    "open the dashboard",
                    "Opening it now.",
                    channel="telegram",
                    channel_scope="42",
                    metadata={"kind": "chat_reply"},
                )

                rows = rs.recent_conversation_turns(limit=2, channel="telegram", channel_scope="42")
                state = rs.get_channel_state("telegram", "42")
                rs._INITIALIZED = False
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "telegram")
        self.assertEqual(rows[0]["channel_scope"], "42")
        self.assertEqual(state["last_user_text"], "open the dashboard")
        self.assertEqual(state["last_assistant_text"], "Opening it now.")


if __name__ == "__main__":
    unittest.main()
