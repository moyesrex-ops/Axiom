import unittest
from unittest.mock import patch

from core import trade_daemon as td


class TradeDaemonTests(unittest.TestCase):
    def test_collect_status_preserves_zero_confidence_threshold(self):
        runtime = {
            "trade_daemon": {
                "enabled": True,
                "auto_start": True,
                "cycle_interval_seconds": 180,
                "max_symbols_per_cycle": 1,
                "max_new_trades_per_cycle": 1,
                "max_open_positions": 5,
                "default_volume": 0.01,
                "min_confidence": 0,
                "allowed_groups": ["Forex"],
            }
        }

        with patch.object(td, "load_runtime_config", return_value=runtime):
            status = td.collect_trade_daemon_status()

        self.assertEqual(status["min_confidence"], 0)


if __name__ == "__main__":
    unittest.main()
