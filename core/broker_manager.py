# core/broker_manager.py
# AXIOM — Universal Broker Manager
#
# Provides a unified abstraction layer over all supported markets:
#   - MetaTrader 5 (Forex / CFDs)
#   - ccxt (Crypto: Binance, Coinbase, Bybit, etc.)
#
# Every position dict returned by get_all_positions() is normalised to:
#   {
#       "market":         str,   # e.g. "Forex/MT5", "Crypto/Binance"
#       "symbol":         str,
#       "type":           str,   # "BUY" | "SELL" | "LONG" | "SHORT" | "HOLDING"
#       "unrealized_pnl": float,
#       "ticket":         str,   # unique identifier
#       "volume":         float,
#       "open_price":     float,
#   }

import json
import logging
from pathlib import Path
import sys

logger = logging.getLogger("BrokerManager")

# ── optional dependencies (safe imports) ────────────────────────────────────

try:
    import MetaTrader5 as _mt5_lib
except ImportError:
    _mt5_lib = None
    logger.warning("[BrokerManager] MetaTrader5 not installed. MT5 market data unavailable.")

try:
    import ccxt as _ccxt_lib
except ImportError:
    _ccxt_lib = None
    logger.warning(
        "[BrokerManager] ccxt not installed. Crypto market data unavailable. "
        "Run: pip install ccxt"
    )

# ── helpers ──────────────────────────────────────────────────────────────────

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _load_api_keys() -> dict:
    path = _get_base_dir() / "config" / "api_keys.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ── Broker Manager ────────────────────────────────────────────────────────────

class BrokerManager:
    """
    Universal market interface.  Aggregates open positions from every
    connected exchange into a single standardised list.
    """

    def __init__(self, api_keys: dict = None):
        self.api_keys = api_keys or _load_api_keys()
        self._crypto_exchange = None
        self._init_crypto()

    # ── initialisation ───────────────────────────────────────────────────────

    def _init_crypto(self):
        if _ccxt_lib is None:
            return
        try:
            exchange_id = self.api_keys.get("ccxt_exchange", "binance")
            api_key     = self.api_keys.get("binance_api") or self.api_keys.get("ccxt_api_key", "")
            secret      = self.api_keys.get("binance_secret") or self.api_keys.get("ccxt_secret", "")

            if not api_key or not secret:
                logger.info("[BrokerManager] No ccxt API keys found — crypto exchange not initialised.")
                return

            exchange_class = getattr(_ccxt_lib, exchange_id, None)
            if exchange_class is None:
                logger.warning(f"[BrokerManager] Unknown ccxt exchange: {exchange_id}")
                return

            self._crypto_exchange = exchange_class({
                "apiKey":          api_key,
                "secret":          secret,
                "enableRateLimit": True,
                "options":         {"defaultType": "future"},
            })
            logger.info(f"[BrokerManager] ✅ Crypto exchange ({exchange_id}) initialised.")
        except Exception as e:
            logger.warning(f"[BrokerManager] Crypto init failed: {e}")

    # ── public API ────────────────────────────────────────────────────────────

    def get_all_positions(self) -> list:
        """
        Returns a normalised list of all open positions across every
        connected broker / exchange.
        """
        positions = []
        positions.extend(self._get_mt5_positions())
        positions.extend(self._get_crypto_positions())
        return positions

    def close_position_by_ticket(self, ticket: str) -> bool:
        """
        Attempt to close a specific position identified by its ticket.
        Returns True on success.
        """
        # MT5 close
        if _mt5_lib is not None:
            try:
                pos_list = _mt5_lib.positions_get()
                if pos_list:
                    for p in pos_list:
                        if str(p.ticket) == str(ticket):
                            return self._close_mt5_position(p)
            except Exception as e:
                logger.warning(f"[BrokerManager] MT5 close error: {e}")

        # Crypto close — ticket format "ccxt:<exchange>:<id>"
        if str(ticket).startswith("ccxt:") and self._crypto_exchange:
            try:
                _, _exch, order_id = ticket.split(":", 2)
                self._crypto_exchange.cancel_order(order_id)
                logger.info(f"[BrokerManager] Crypto order {order_id} cancelled.")
                return True
            except Exception as e:
                logger.warning(f"[BrokerManager] Crypto close error: {e}")

        return False

    # ── private helpers ───────────────────────────────────────────────────────

    def _get_mt5_positions(self) -> list:
        if _mt5_lib is None:
            return []
        try:
            info = _mt5_lib.terminal_info()
            if info is None:
                return []
            raw = _mt5_lib.positions_get()
            if not raw:
                return []
            result = []
            for p in raw:
                tick = _mt5_lib.symbol_info_tick(p.symbol)
                open_price = p.price_open
                result.append({
                    "market":         "Forex/MT5",
                    "symbol":         p.symbol,
                    "type":           "BUY" if p.type == _mt5_lib.ORDER_TYPE_BUY else "SELL",
                    "unrealized_pnl": float(p.profit),
                    "ticket":         str(p.ticket),
                    "volume":         float(p.volume),
                    "open_price":     float(open_price),
                    "_raw":           p,  # keep raw for MT5 close ops
                })
            return result
        except Exception as e:
            logger.warning(f"[BrokerManager] MT5 position fetch error: {e}")
            return []

    def _get_crypto_positions(self) -> list:
        if self._crypto_exchange is None:
            return []
        try:
            positions = self._crypto_exchange.fetch_positions()
            result = []
            for pos in positions:
                notional = pos.get("notional") or pos.get("initialMargin") or 0
                if not notional or notional == 0:
                    continue
                side = pos.get("side", "long").upper()
                result.append({
                    "market":         f"Crypto/{self._crypto_exchange.id}",
                    "symbol":         pos.get("symbol", "UNKNOWN"),
                    "type":           "LONG" if side == "LONG" else "SHORT",
                    "unrealized_pnl": float(pos.get("unrealizedPnl") or 0),
                    "ticket":         f"ccxt:{self._crypto_exchange.id}:{pos.get('id', 'unknown')}",
                    "volume":         float(pos.get("contracts") or 0),
                    "open_price":     float(pos.get("entryPrice") or 0),
                })
            return result
        except Exception as e:
            logger.warning(f"[BrokerManager] Crypto position fetch error: {e}")
            return []

    def _close_mt5_position(self, p) -> bool:
        """Close a single MT5 position."""
        try:
            tick        = _mt5_lib.symbol_info_tick(p.symbol)
            price       = tick.bid if p.type == _mt5_lib.ORDER_TYPE_BUY else tick.ask
            action_type = _mt5_lib.ORDER_TYPE_SELL if p.type == _mt5_lib.ORDER_TYPE_BUY else _mt5_lib.ORDER_TYPE_BUY
            req = {
                "action":       _mt5_lib.TRADE_ACTION_DEAL,
                "symbol":       p.symbol,
                "volume":       p.volume,
                "type":         action_type,
                "position":     p.ticket,
                "price":        price,
                "deviation":    20,
                "magic":        234000,
                "comment":      "BrokerManager Auto-Close",
                "type_time":    _mt5_lib.ORDER_TIME_GTC,
                "type_filling": _mt5_lib.ORDER_FILLING_IOC,
            }
            res = _mt5_lib.order_send(req)
            return res is not None and res.retcode == _mt5_lib.TRADE_RETCODE_DONE
        except Exception as e:
            logger.warning(f"[BrokerManager] MT5 close failed: {e}")
            return False
