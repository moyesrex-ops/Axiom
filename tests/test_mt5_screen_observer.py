import unittest
from types import SimpleNamespace
from unittest.mock import patch

from actions import mt5_screen_observer as obs


class MT5ScreenObserverTests(unittest.TestCase):
    def test_fallback_snapshot_extracts_symbol_timeframe_and_errors(self):
        snapshot = obs._fallback_snapshot(
            "MetaTrader 5 chart for XAUUSD on M15. Order failed retcode visible.",
            "",
            symbol_hint="XAUUSD",
        )

        self.assertTrue(snapshot["mt5_visible"])
        self.assertEqual(snapshot["symbol"], "XAUUSD")
        self.assertEqual(snapshot["timeframe"], "M15")
        self.assertIn("order failed", snapshot["execution_error"])

    @patch.object(
        obs.gn,
        "generate_json",
        return_value={
            "mt5_visible": True,
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "positions_visible": True,
            "open_positions_count": 2,
            "floating_pl": "+12.40",
            "balance": "1000.00",
            "equity": "1012.40",
            "chart_bias": "bullish",
            "execution_error": "",
            "confidence": 0.82,
            "summary": "MT5 is visible with XAUUSD on M5 and two open positions.",
        },
    )
    @patch.object(
        obs,
        "analyze_screen",
        return_value=SimpleNamespace(description="MetaTrader 5 is visible.", text_content="XAUUSD M5"),
    )
    def test_observe_mt5_screen_returns_structured_snapshot(self, _analyze_mock, _json_mock):
        snapshot = obs.observe_mt5_screen("XAUUSD")

        self.assertTrue(snapshot["mt5_visible"])
        self.assertEqual(snapshot["symbol"], "XAUUSD")
        self.assertEqual(snapshot["timeframe"], "M5")
        self.assertEqual(snapshot["chart_bias"], "bullish")


if __name__ == "__main__":
    unittest.main()
