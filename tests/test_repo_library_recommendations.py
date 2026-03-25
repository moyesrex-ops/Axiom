import unittest
from pathlib import Path
import shutil
from unittest.mock import patch

from core import agent_library, skill_library


class RepoLibraryRecommendationTests(unittest.TestCase):
    def test_frontend_task_prefers_impeccable_and_uncodixfy(self):
        entries = [
            {
                "id": "impeccable:frontend-design",
                "source_id": "impeccable",
                "source_name": "Impeccable",
                "slug": "frontend-design",
                "name": "Frontend Design",
                "description": "Intentional frontend design guidance.",
                "content_preview": "typography layout polish",
            },
            {
                "id": "uncodixfy:uncodixfy",
                "source_id": "uncodixfy",
                "source_name": "Uncodixfy",
                "slug": "uncodixfy",
                "name": "Uncodixfy",
                "description": "Avoid generic AI UI patterns.",
                "content_preview": "anti-patterns for UI design",
            },
            {
                "id": "superpowers:debug",
                "source_id": "superpowers",
                "source_name": "Superpowers",
                "slug": "debug",
                "name": "Debug",
                "description": "Debugging workflow.",
                "content_preview": "tracebacks and failures",
            },
        ]

        with patch.object(skill_library, "index_skill_library", return_value=entries):
            rows = skill_library.recommend_skill_library("design a polished landing page UI", limit=2)

        self.assertEqual([row["source_id"] for row in rows], ["impeccable", "uncodixfy"])

    def test_orchestration_task_prefers_symphony_agent_entry(self):
        entries = [
            {
                "id": "symphony:symphony-orchestrator",
                "source_id": "symphony",
                "source_name": "Symphony",
                "slug": "symphony-orchestrator",
                "name": "Symphony Orchestrator",
                "description": "Issue-driven orchestrator with isolated workspaces.",
                "category": "work orchestration",
                "content_preview": "tickets workspaces workflow isolated runs",
            },
            {
                "id": "paperclip:paperclip-control-plane",
                "source_id": "paperclip",
                "source_name": "Paperclip",
                "slug": "paperclip-control-plane",
                "name": "Paperclip Control Plane Operator",
                "description": "Heartbeats budgets governance company orchestration.",
                "category": "company orchestration",
                "content_preview": "heartbeats budgets tasks",
            },
            {
                "id": "openfang:researcher",
                "source_id": "openfang",
                "source_name": "OpenFang",
                "slug": "researcher",
                "name": "Researcher Hand",
                "description": "Autonomous deep researcher.",
                "category": "productivity",
                "content_preview": "research sources reports",
            },
        ]

        with patch.object(agent_library, "index_agent_library", return_value=entries):
            rows = agent_library.recommend_agent_library(
                "orchestrate ticket execution across isolated workspaces in parallel",
                limit=2,
            )

        self.assertEqual(rows[0]["source_id"], "symphony")
        self.assertIn(rows[1]["source_id"], {"paperclip", "openfang"})

    def test_root_level_skill_repo_is_indexed(self):
        repo = Path(__file__).resolve().parent / "_tmp" / "uncodixfy-root-skill"
        shutil.rmtree(repo, ignore_errors=True)
        repo.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(repo, ignore_errors=True))
        (repo / "SKILL.md").write_text(
            "---\nname: Uncodixfy\ndescription: Anti-slop UI rules.\n---\n\n# Uncodixfy\n",
            encoding="utf-8",
        )

        original_specs = skill_library._SOURCE_SPECS
        original_cache = dict(skill_library._INDEX_CACHE)
        try:
            skill_library._SOURCE_SPECS = {
                "uncodixfy": {
                    "name": "Uncodixfy",
                    "config_key": "uncodixfy_path",
                    "default_candidates": [repo],
                    "skills_subdir": ".",
                }
            }
            skill_library._INDEX_CACHE = {"signature": None, "entries": []}
            with patch.object(skill_library, "_runtime_skill_config", return_value={"enabled": True, "uncodixfy_path": str(repo)}):
                rows = skill_library.index_skill_library()
        finally:
            skill_library._SOURCE_SPECS = original_specs
            skill_library._INDEX_CACHE = original_cache

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_id"], "uncodixfy")
        self.assertTrue(rows[0]["slug"])


if __name__ == "__main__":
    unittest.main()
