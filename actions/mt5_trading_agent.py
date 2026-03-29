import json
import threading
import time
from typing import Optional

from actions.mt5_screen_observer import (
    format_mt5_screen_state,
    log_mt5_screen_state,
    observe_mt5_screen,
)
from memory.runtime_store import log_event
from core.runtime_config import load_runtime_config

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


def _get_api_key() -> str:
    import sys
    from pathlib import Path

    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    config_path = base / "config" / "api_keys.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]
    except Exception:
        return ""


def get_base_dir():
    import sys
    from pathlib import Path

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_MONITORED_TICKETS: set = set()
_monitor_lock = threading.Lock()
_monitor_thread: Optional[threading.Thread] = None

POSITION_MONITOR_POLL_INTERVAL = 15
MAX_SOUL_LESSONS_IN_PROMPT = 5
DEFAULT_SL_TP_PIPS = 50


def _trading_config() -> dict:
    return load_runtime_config().get("trading", {}) or {}


def _observe_mt5_screen_if_needed(symbol: str, params: dict, *, force: bool = False) -> dict:
    cfg = _trading_config()
    if not force and not bool(params.get("observe_screen", False)) and not bool(cfg.get("observe_screen_before_execution", False)):
        return {}
    snapshot = observe_mt5_screen(symbol_hint=symbol)
    log_mt5_screen_state(snapshot, topic="mt5_screen_observation", symbol_hint=symbol)
    return snapshot


def _screen_observation_block_reason(snapshot: dict, symbol: str) -> str:
    if not snapshot:
        return ""
    cfg = _trading_config()
    expected_symbol = str(symbol or "").strip().upper()
    observed_symbol = str(snapshot.get("symbol", "") or "").strip().upper()
    if bool(cfg.get("require_screen_confirmation", False)) and not bool(snapshot.get("mt5_visible", False)):
        return "Pre-trade MT5 screen check did not detect a visible MetaTrader 5 terminal."
    if bool(cfg.get("require_symbol_match", False)) and expected_symbol and observed_symbol and observed_symbol != expected_symbol:
        return f"Pre-trade MT5 screen check saw {observed_symbol}, not {expected_symbol}."
    return ""


def _account_is_demo(account_info) -> bool:
    if account_info is None or mt5 is None:
        return False
    server = str(getattr(account_info, "server", "") or "").lower()
    trade_mode = int(getattr(account_info, "trade_mode", -1) or -1)
    demo_mode = int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
    return "demo" in server or trade_mode == demo_mode


def _position_monitor_loop():
    if mt5 is None:
        return
    while True:
        try:
            if not mt5.initialize():
                time.sleep(10)
                continue

            positions = mt5.positions_get()
            open_tickets = {p.ticket for p in positions} if positions else set()

            with _monitor_lock:
                closed = _MONITORED_TICKETS - open_tickets
                _MONITORED_TICKETS.update(open_tickets)
                _MONITORED_TICKETS.difference_update(closed)

            if closed:
                from_time = int(time.time()) - 86400
                deals = mt5.history_deals_get(from_time, int(time.time()))
                if deals:
                    for deal in deals:
                        if deal.position_id in closed:
                            try:
                                from memory.trading_soul import reflect_on_trade

                                reflect_on_trade(
                                    symbol=deal.symbol,
                                    profit=deal.profit,
                                    reason=f"Deal type {deal.type}, comment: {deal.comment}",
                                )
                                print(
                                    f"[MT5] Reflected on closed position {deal.position_id} "
                                    f"({deal.symbol}, P&L: {deal.profit})"
                                )
                            except Exception as e:
                                print(f"[MT5] Reflection error: {e}")

            mt5.shutdown()
        except Exception as e:
            print(f"[MT5 Monitor] {e}")
        time.sleep(POSITION_MONITOR_POLL_INTERVAL)


def _ensure_monitor_running():
    global _monitor_thread
    if _monitor_thread is not None and _monitor_thread.is_alive():
        return
    _monitor_thread = threading.Thread(
        target=_position_monitor_loop,
        daemon=True,
        name="MT5PositionMonitor",
    )
    _monitor_thread.start()
    print("[MT5] Position monitor started.")


def mt5_trading(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = params.get("action", "").lower()
    symbol_filter = str(params.get("symbol", "") or "").strip()
    symbol = symbol_filter or "EURUSD"
    volume = float(params.get("volume", 0.01))
    magic = int(params.get("magic", 234000))
    prompt_raw = params.get("prompt", "")
    stop_loss = params.get("stop_loss")
    take_profit = params.get("take_profit")

    if action in ("screen_state", "observe_screen", "screen"):
        snapshot = _observe_mt5_screen_if_needed(symbol, params, force=True)
        if not snapshot:
            snapshot = observe_mt5_screen(symbol_hint=symbol)
            log_mt5_screen_state(snapshot, topic="mt5_screen_observation", symbol_hint=symbol)
        report = format_mt5_screen_state(snapshot)
        if speak:
            speak(report)
        return report

    if mt5 is None:
        message = (
            "MetaTrader5 is not installed in the current Python environment. "
            "Please run 'pip install MetaTrader5' to enable ultra-low latency native trading."
        )
        log_event("trading", "mt5_unavailable", message)
        return message

    if not mt5.initialize():
        message = f"Failed to initialize MT5, error: {mt5.last_error()}"
        log_event("trading", "mt5_initialize_failed", message)
        return message

    if action == "info":
        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            return f"Failed to get account info: {mt5.last_error()}"

        positions = (
            mt5.positions_get(symbol=symbol_filter)
            if symbol_filter
            else mt5.positions_get()
        )
        positions = list(positions or [])
        floating_pl = sum(float(getattr(position, "profit", 0.0) or 0.0) for position in positions)

        lines = [
            (
                f"MT5 Connected. Balance: {account_info.balance:.2f}, "
                f"Equity: {account_info.equity:.2f}, Margin: {account_info.margin:.2f}, "
                f"Open positions: {len(positions)}, Floating P/L: {floating_pl:.2f}"
            ),
            f"Server: {account_info.server} | Demo account: {'yes' if _account_is_demo(account_info) else 'no'}",
        ]

        if positions:
            lines.append("Open positions:")
            for position in positions[:6]:
                side = "BUY" if getattr(position, "type", None) == mt5.ORDER_TYPE_BUY else "SELL"
                lines.append(
                    (
                        f"- #{position.ticket} {position.symbol} {side} "
                        f"{float(position.volume):.2f} lots | entry {float(position.price_open):.5f} "
                        f"| current {float(position.price_current):.5f} | P/L {float(position.profit):.2f}"
                    )
                )
            if len(positions) > 6:
                lines.append(f"- ... {len(positions) - 6} more open positions")
        else:
            lines.append("No open positions right now.")

        res = "\n".join(lines)
        if speak:
            speak(res)
        log_event(
            "trading",
            "mt5_info",
            res[:1500],
            metadata={"symbol_filter": symbol_filter, "positions": len(positions)},
        )
        mt5.shutdown()
        return res

    if prompt_raw and action not in ("buy", "sell"):
        try:
            from core import gemini_compat as genai

            genai.configure(api_key=_get_api_key())

            soul_path = get_base_dir() / "memory" / "trading_soul.json"
            soul_lessons = ""
            if soul_path.exists():
                try:
                    with open(soul_path, "r", encoding="utf-8") as f:
                        soul_data = json.load(f)
                        lessons = soul_data.get("lessons_learned", [])
                        if lessons:
                            soul_lessons = "\n".join(
                                [f"- {l['lesson']}" for l in lessons[-MAX_SOUL_LESSONS_IN_PROMPT:]]
                            )
                except Exception:
                    pass

            model = genai.GenerativeModel("gemini-3-flash-preview")
            prompt = f"""
            [MT5 EXECUTION ENGINE: MULTIMODAL EXTRACTION]
            Extract parameters for a trade from this intent: "{prompt_raw}"

            UNBREAKABLE TRADING SOUL LESSONS:
            {soul_lessons if soul_lessons else "No past lessons."}

            Output strictly a JSON object (always include stop_loss and take_profit):
            {{"symbol": "STRING", "volume": FLOAT, "action": "buy/sell", "stop_loss": FLOAT, "take_profit": FLOAT}}
            """

            response = model.generate_content(prompt)
            raw_text = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw_text)
            action = data.get("action", "").lower()
            symbol = data.get("symbol", "EURUSD")
            volume = float(data.get("volume", 0.01))
            stop_loss = data.get("stop_loss")
            take_profit = data.get("take_profit")
        except Exception as e:
            message = f"Parameter extraction failed: {e}"
            log_event("trading", "mt5_parameter_extraction_failed", message[:1000], metadata={"prompt": str(prompt_raw)[:300]})
            return message

    if action in ("buy", "sell"):
        if speak:
            speak(f"Executing {action} order for {volume} lots on {symbol}.")

        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            message = f"Failed to get MT5 account info: {mt5.last_error()}"
            log_event("trading", "mt5_account_info_failed", message)
            return message

        trading_cfg = _trading_config()
        max_volume = float(trading_cfg.get("max_order_volume", 0.10) or 0.10)
        require_demo = bool(trading_cfg.get("require_demo_account_for_live_orders", True))
        if require_demo and not _account_is_demo(account_info):
            mt5.shutdown()
            message = (
                f"Live MT5 execution is restricted to demo accounts. "
                f"Current server: {account_info.server or 'unknown'}"
            )
            log_event("trading", "mt5_demo_guard_blocked", message, metadata={"server": str(account_info.server or "")})
            return message
        if max_volume > 0 and volume > max_volume:
            mt5.shutdown()
            message = f"Requested MT5 volume {volume:.2f} exceeds configured max_order_volume {max_volume:.2f}."
            log_event(
                "trading",
                "mt5_volume_guard_blocked",
                message,
                metadata={"volume": float(volume), "max_volume": max_volume, "symbol": symbol},
            )
            return message

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            mt5.shutdown()
            message = f"Symbol {symbol} not found in MetaTrader."
            log_event("trading", "mt5_symbol_missing", message, metadata={"symbol": symbol})
            return message

        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                mt5.shutdown()
                message = f"Symbol {symbol} select failed."
                log_event("trading", "mt5_symbol_select_failed", message, metadata={"symbol": symbol})
                return message

        order_type = mt5.ORDER_TYPE_BUY if action == "buy" else mt5.ORDER_TYPE_SELL

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            mt5.shutdown()
            message = f"Could not get tick data for {symbol}."
            log_event("trading", "mt5_tick_failed", message, metadata={"symbol": symbol})
            return message

        screen_snapshot = _observe_mt5_screen_if_needed(symbol, params)
        block_reason = _screen_observation_block_reason(screen_snapshot, symbol)
        if block_reason:
            mt5.shutdown()
            log_event("trading", "mt5_screen_guard_blocked", block_reason, metadata={"symbol": symbol})
            return block_reason

        price = tick.ask if action == "buy" else tick.bid
        point = symbol_info.point

        default_sl_tp_pips = int(trading_cfg.get("default_sl_tp_pips", DEFAULT_SL_TP_PIPS) or DEFAULT_SL_TP_PIPS)
        pip_distance = default_sl_tp_pips * 10 * point
        if stop_loss is None:
            stop_loss = round(
                price - pip_distance if action == "buy" else price + pip_distance,
                symbol_info.digits,
            )
        if take_profit is None:
            take_profit = round(
                price + pip_distance if action == "buy" else price - pip_distance,
                symbol_info.digits,
            )

        try:
            stop_loss = round(float(stop_loss), symbol_info.digits)
            take_profit = round(float(take_profit), symbol_info.digits)
        except (TypeError, ValueError):
            stop_loss = None
            take_profit = None

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": magic,
            "comment": "Axiom v4 Omni",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if stop_loss is not None:
            request["sl"] = stop_loss
        if take_profit is not None:
            request["tp"] = take_profit

        result = mt5.order_send(request)

        if result is None:
            error = f"Order send failed completely. ({mt5.last_error()})"
            log_event("trading", "mt5_order_failed", error, metadata={"symbol": symbol, "action": action, "volume": volume})
            mt5.shutdown()
            return error

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error = f"Order failed, retcode={result.retcode} ({mt5.last_error()})"
            log_event(
                "trading",
                "mt5_order_failed",
                error,
                metadata={"symbol": symbol, "action": action, "volume": volume, "retcode": int(result.retcode)},
            )
            mt5.shutdown()
            return error

        sl_info = f", SL: {stop_loss}" if stop_loss else ""
        tp_info = f", TP: {take_profit}" if take_profit else ""
        msg = (
            f"Order placed! Ticket: {result.order}, Price: {result.price}, "
            f"Volume: {result.volume}{sl_info}{tp_info}"
        )
        log_event(
            "trading",
            "mt5_order_placed",
            msg,
            metadata={
                "symbol": symbol,
                "action": action,
                "volume": float(volume),
                "ticket": int(result.order),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "magic": magic,
            },
        )
        if speak:
            speak("Order successfully executed in the market.")
        with _monitor_lock:
            _MONITORED_TICKETS.add(result.order)
        _ensure_monitor_running()
        mt5.shutdown()
        return msg

    mt5.shutdown()
    message = f"Unknown action: {action}. Supported: info, buy, sell."
    log_event("trading", "mt5_unknown_action", message)
    return message
