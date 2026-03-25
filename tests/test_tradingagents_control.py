import unittest
from unittest.mock import patch

from actions import tradingagents_control as tac


class TradingAgentsControlTests(unittest.TestCase):
    @staticmethod
    def _analysis_result() -> dict:
        return {
            "ok": True,
            "ticker": "EURUSD",
            "trade_date": "2026-03-25",
            "decision": "BUY | CONFIDENCE: 72%",
            "final_trade_decision": "BUY EURUSD with stop loss 1.0825 and take profit 1.0940",
            "investment_plan": "",
            "trader_investment_plan": "",
            "run_file": "C:/tmp/tradingagents_run.json",
        }

    @patch.object(tac, "save_to_nexus")
    @patch.object(tac, "log_event")
    @patch.object(tac, "mt5_trading")
    @patch.object(tac, "run_tradingagents_analysis")
    def test_execute_mt5_defaults_to_dry_run(self, run_mock, mt5_mock, _log_mock, _save_mock):
        run_mock.return_value = self._analysis_result()

        report = tac.tradingagents_control({"action": "execute_mt5", "ticker": "EURUSD"})

        mt5_mock.assert_not_called()
        self.assertIn("Derived action: buy", report)
        self.assertIn("Execution mode: dry run only", report)
        self.assertIn("Set confirm=true", report)

    @patch.object(tac, "save_to_nexus")
    @patch.object(tac, "log_event")
    @patch.object(tac, "mt5_trading", return_value="Order placed! Ticket: 123")
    @patch.object(tac, "run_tradingagents_analysis")
    def test_execute_mt5_calls_mt5_when_confirmed(self, run_mock, mt5_mock, _log_mock, _save_mock):
        run_mock.return_value = self._analysis_result()

        report = tac.tradingagents_control(
            {
                "action": "execute_mt5",
                "ticker": "EURUSD",
                "confirm": True,
                "volume": 0.02,
            }
        )

        mt5_mock.assert_called_once()
        call = mt5_mock.call_args.args[0]
        self.assertEqual(call["action"], "buy")
        self.assertEqual(call["symbol"], "EURUSD")
        self.assertEqual(call["volume"], 0.02)
        self.assertIn("MT5 result: Order placed! Ticket: 123", report)


if __name__ == "__main__":
    unittest.main()
