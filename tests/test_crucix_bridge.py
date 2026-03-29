import unittest
from unittest.mock import patch

from core import crucix_bridge as cb


class CrucixBridgeTests(unittest.TestCase):
    def test_runtime_env_inherits_axiom_gemini_defaults(self):
        runtime = {
            "crucix": {
                "inherit_axiom_gemini": True,
                "llm_provider": "gemini",
                "llm_model": "",
            },
            "text_models": {
                "fast": "gemini-2.5-flash-lite",
                "default": "gemini-2.5-flash",
            },
        }

        with patch.object(cb, "load_runtime_config", return_value=runtime), patch.object(
            cb, "get_gemini_api_key", return_value="secret-key"
        ), patch.dict(cb.os.environ, {}, clear=True):
            env = cb._crucix_runtime_env()

        self.assertEqual(env["LLM_PROVIDER"], "gemini")
        self.assertEqual(env["LLM_API_KEY"], "secret-key")
        self.assertEqual(env["LLM_MODEL"], "gemini-2.5-flash-lite")

    def test_market_context_surfaces_asset_relevant_headlines(self):
        status = {
            "repo_path": "C:/Crucix",
            "server_url": "http://127.0.0.1:3117",
            "reachable": True,
            "last_sweep": "2026-03-29T13:36:42.570Z",
            "llm_enabled": True,
            "llm_provider": "gemini",
        }
        payload = {
            "markets": {
                "commodities": [
                    {"symbol": "GC=F", "name": "Gold", "price": 4524.3, "changePct": 2.84},
                ],
                "vix": {"value": 31.05, "changePct": 18.74},
            },
            "newsFeed": [
                {"headline": "Gold jumps as Fed fears return", "source": "Example", "region": "US", "urgent": True},
                {"headline": "Tech earnings mixed", "source": "Example", "region": "US", "urgent": False},
            ],
            "tg": {
                "urgent": [
                    {"channel": "intel", "text": "Gold safe haven flow accelerating after regional strike"},
                ]
            },
            "ideas": [
                {"title": "Gold breakout continuation", "summary": "Momentum remains strong"},
            ],
            "energy": {"wti": 99.64, "brent": 105.32},
        }

        with patch.object(cb, "collect_crucix_status", return_value=status), patch.object(
            cb, "_http_json", return_value=(payload, "")
        ):
            context = cb.get_crucix_market_context("XAUUSD", limit=3)

        self.assertTrue(context["reachable"])
        self.assertTrue(context["market_snapshot"])
        self.assertEqual(context["relevant_headlines"][0]["headline"], "Gold jumps as Fed fears return")
        self.assertEqual(context["ideas"][0]["title"], "Gold breakout continuation")


if __name__ == "__main__":
    unittest.main()
