import unittest
from unittest.mock import patch

from core import doctor


class DoctorTests(unittest.TestCase):
    def test_doctor_report_surfaces_gemini_first_and_optional_integrations(self):
        with patch.object(doctor, "load_runtime_config", return_value={"browser": {"backend": "playwright"}, "channels": {"telegram": {"enabled": False}}, "integrations": {}, "deerflow": {}}), patch.object(
            doctor, "get_secret", return_value="secret"
        ), patch.object(doctor, "_memory_store_status", return_value={"ok": True, "db_path": "memory/axiom_state.db"}), patch.object(
            doctor, "_has_module", return_value=True
        ), patch.object(
            doctor, "collect_mirofish_status", return_value={"repo_path": "", "backend_reachable": False, "server_url": ""}
        ), patch.object(
            doctor,
            "collect_automaton_status",
            return_value={
                "repo_path": "automaton",
                "built_entry": "dist/index.js",
                "config_path": "",
                "db_path": "",
                "soul_path": "",
                "api_key_present": False,
            },
        ), patch.object(
            doctor, "collect_lightpanda_status", return_value={"repo_path": "", "reachable": False, "endpoint": "http://127.0.0.1:9222"}
        ), patch.object(
            doctor, "collect_autoresearch_status", return_value={"repo_path": "", "uv_available": False, "tokenizer_ready": False, "data_shards": 0}
        ), patch.object(
            doctor, "collect_deerflow_status", return_value={"repo_path": "deerflow", "proxy_reachable": False, "gateway_url": "http://127.0.0.1:2026"}
        ), patch.object(
            doctor, "collect_skill_library_status", return_value={"enabled": True, "total_skills": 10, "sources_count": 2}
        ), patch.object(
            doctor, "collect_agent_library_status", return_value={"enabled": True, "total_agents": 200, "sources_count": 4}
        ), patch.object(
            doctor, "collect_dexter_status", return_value={"repo_path": "dexter", "bun_available": True}
        ), patch.object(
            doctor, "collect_pentagi_status", return_value={"repo_path": "pentagi", "audit_notice_present": True, "source_available": False}
        ), patch.object(
            doctor, "_has_command", return_value=True
        ):
            report = doctor.format_doctor_report(limit=4)

        self.assertIn("Agent Library: 200 indexed agents across 4 sources", report)
        self.assertIn("Dexter: Repo detected and Bun available", report)
        self.assertIn("PentAGI: Repo detected but upstream source is currently unavailable", report)
        self.assertIn("Gemini-First Startup: Base startup path is ready with Gemini; optional integrations are additive", report)
        self.assertIn("Automaton: Optional repo detected but runtime is not enabled", report)
        self.assertIn("DeerFlow: Optional harness is installed but not running", report)
        self.assertIn("Codex Builder: Codex CLI available", report)


if __name__ == "__main__":
    unittest.main()
