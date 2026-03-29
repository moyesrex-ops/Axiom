import unittest
from unittest.mock import patch

from actions import mt5_trading_agent as mt5a


class MT5TradingAgentTests(unittest.TestCase):
    @patch.object(mt5a, "format_mt5_screen_state", return_value="MT5 screen state")
    @patch.object(mt5a, "observe_mt5_screen", return_value={"mt5_visible": True, "symbol": "XAUUSD"})
    @patch.object(mt5a, "log_mt5_screen_state")
    def test_screen_state_action_returns_observer_report(self, _log_mock, observe_mock, format_mock):
        report = mt5a.mt5_trading({"action": "screen_state", "symbol": "XAUUSD"})

        self.assertEqual(report, "MT5 screen state")
        observe_mock.assert_called_once_with(symbol_hint="XAUUSD")
        format_mock.assert_called_once()

    def test_screen_guard_reason_respects_runtime_flags(self):
        with patch.object(mt5a, "_trading_config", return_value={"require_screen_confirmation": True, "require_symbol_match": True}):
            reason = mt5a._screen_observation_block_reason({"mt5_visible": False, "symbol": "EURUSD"}, "XAUUSD")

        self.assertIn("did not detect", reason)


if __name__ == "__main__":
    unittest.main()
