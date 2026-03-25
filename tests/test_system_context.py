import unittest
from unittest.mock import patch

from core import system_context as sc


class SystemContextTests(unittest.TestCase):
    def setUp(self):
        sc._CACHE_AT = 0.0
        sc._CACHE_DATA = {}
        sc._CACHE_SIGNATURE = ""

    def test_public_lookup_stays_off_when_disabled(self):
        with patch.object(
            sc, "load_runtime_config", return_value={"system_context": {"enable_public_ip_lookup": False}}
        ), patch.object(sc, "_public_ip_context", side_effect=AssertionError("should not call")):
            ctx = sc.collect_system_context(force_refresh=True)

        self.assertFalse(ctx["public_ip_lookup_enabled"])

    def test_public_lookup_runs_when_enabled(self):
        with patch.object(
            sc, "load_runtime_config", return_value={"system_context": {"enable_public_ip_lookup": True}}
        ), patch.object(
            sc,
            "_public_ip_context",
            return_value={"city": "Test City", "country": "Test Country", "timezone_name": "UTC"},
        ):
            ctx = sc.collect_system_context(force_refresh=True)

        self.assertTrue(ctx["public_ip_lookup_enabled"])
        self.assertEqual(ctx["city"], "Test City")
        self.assertEqual(ctx["country"], "Test Country")


if __name__ == "__main__":
    unittest.main()
