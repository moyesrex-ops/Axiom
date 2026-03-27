import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from core import runtime_config as rc


class RuntimeConfigTests(unittest.TestCase):
    def _workspace_dir(self, name: str) -> Path:
        root = Path(__file__).resolve().parent / "_tmp"
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_load_runtime_config_merges_local_over_base(self):
        config_dir = self._workspace_dir("runtime_config")
        runtime_path = config_dir / "runtime.json"
        local_path = config_dir / "runtime.local.json"

        runtime_path.write_text(
            json.dumps(
                {
                    "channels": {"telegram": {"enabled": True}},
                    "integrations": {"mirofish_path": "base-path"},
                }
            ),
            encoding="utf-8",
        )
        local_path.write_text(
            json.dumps(
                {
                    "integrations": {"mirofish_path": "local-path"},
                    "system_context": {"enable_public_ip_lookup": True},
                }
            ),
            encoding="utf-8",
        )

        with patch.object(rc, "CONFIG_DIR", config_dir), patch.object(
            rc, "RUNTIME_CONFIG_PATH", runtime_path
        ), patch.object(rc, "RUNTIME_LOCAL_CONFIG_PATH", local_path):
            loaded = rc.load_runtime_config()

            self.assertTrue(loaded["channels"]["telegram"]["enabled"])
            self.assertEqual(loaded["integrations"]["mirofish_path"], "local-path")
            self.assertTrue(loaded["system_context"]["enable_public_ip_lookup"])
            self.assertTrue(loaded["live"]["enable_context_window_compression"])


if __name__ == "__main__":
    unittest.main()
