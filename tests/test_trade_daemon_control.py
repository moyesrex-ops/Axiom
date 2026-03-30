import unittest
from unittest.mock import patch

from actions import trade_daemon_control as tdc


class TradeDaemonControlTests(unittest.TestCase):
    @patch.object(tdc, "log_event")
    @patch.object(tdc, "format_trade_daemon_status", return_value="[TRADE DAEMON]\nRunning: no")
    def test_status_returns_formatted_report(self, status_mock, _log_mock):
        report = tdc.trade_daemon_control({"action": "status"})

        status_mock.assert_called_once()
        self.assertIn("[TRADE DAEMON]", report)

    @patch.object(tdc, "log_event")
    @patch.object(tdc, "configure_trade_daemon", return_value={"trade_daemon": {"enabled": True, "auto_start": True}})
    def test_configure_updates_runtime(self, configure_mock, _log_mock):
        report = tdc.trade_daemon_control({"action": "configure", "enabled": True, "auto_start": True})

        configure_mock.assert_called_once_with({"enabled": True, "auto_start": True})
        self.assertIn("Trade daemon configuration updated", report)

    @patch.object(tdc, "log_event")
    @patch.object(tdc, "trigger_trade_daemon_cycle", return_value="Trade daemon wake requested.")
    def test_run_once_delegates_to_cycle_trigger(self, trigger_mock, _log_mock):
        report = tdc.trade_daemon_control({"action": "run_once"})

        trigger_mock.assert_called_once()
        self.assertEqual(report, "Trade daemon wake requested.")


if __name__ == "__main__":
    unittest.main()
