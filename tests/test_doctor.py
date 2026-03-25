import unittest
from unittest.mock import patch

from core import doctor


class DoctorTests(unittest.TestCase):
    def test_doctor_report_surfaces_new_agent_and_integration_checks(self):
        with patch.object(doctor, "load_runtime_config", return_value={"browser": {"backend": "playwright"}, "channels": {"telegram": {"enabled": False}}}), patch.object(
            doctor, "get_secret", return_value="secret"
        ), patch.object(doctor, "_memory_store_status", return_value={"ok": True, "db_path": "memory/axiom_state.db"}), patch.object(
            doctor, "_has_module", return_value=True
        ), patch.object(
            doctor, "collect_mirofish_status", return_value={"repo_path": "", "backend_reachable": False, "server_url": ""}
        ), patch.object(
            doctor, "collect_automaton_status", return_value={"repo_path": "", "built_entry": False}
        ), patch.object(
            doctor, "collect_lightpanda_status", return_value={"repo_path": "", "reachable": False, "endpoint": "http://127.0.0.1:9222"}
        ), patch.object(
            doctor, "collect_autoresearch_status", return_value={"repo_path": "", "uv_available": False, "tokenizer_ready": False, "data_shards": 0}
        ), patch.object(
            doctor, "collect_skill_library_status", return_value={"enabled": True, "total_skills": 10, "sources_count": 2}
        ), patch.object(
            doctor, "collect_agent_library_status", return_value={"enabled": True, "total_agents": 200, "sources_count": 4}
        ), patch.object(
            doctor, "collect_dexter_status", return_value={"repo_path": "dexter", "bun_available": True}
        ), patch.object(
            doctor, "collect_pentagi_status", return_value={"repo_path": "pentagi", "audit_notice_present": True, "source_available": False}
        ):
            report = doctor.format_doctor_report(limit=4)

        self.assertIn("Agent Library: 200 indexed agents across 4 sources", report)
        self.assertIn("Dexter: Repo detected and Bun available", report)
        self.assertIn("PentAGI: Repo detected but upstream source is currently unavailable", report)


if __name__ == "__main__":
    unittest.main()
