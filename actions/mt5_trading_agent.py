import json
import threading
import time
from typing import Optional

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
    symbol = params.get("symbol", "EURUSD")
    volume = float(params.get("volume", 0.01))
    magic = int(params.get("magic", 234000))
    prompt_raw = params.get("prompt", "")
    stop_loss = params.get("stop_loss")
    take_profit = params.get("take_profit")

    if mt5 is None:
        return (
            "MetaTrader5 is not installed in the current Python environment. "
            "Please run 'pip install MetaTrader5' to enable ultra-low latency native trading."
        )

    if not mt5.initialize():
        return f"Failed to initialize MT5, error: {mt5.last_error()}"

    if action == "info":
        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            return f"Failed to get account info: {mt5.last_error()}"
        res = (
            f"MT5 Connected. Balance: {account_info.balance:.2f}, "
            f"Equity: {account_info.equity:.2f}, Margin: {account_info.margin:.2f}"
        )
        if speak:
            speak(res)
        mt5.shutdown()
        return res

    if prompt_raw and action not in ("buy", "sell"):
        try:
            import google.generativeai as genai

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

            model = genai.GenerativeModel("gemini-2.5-flash")
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
            return f"Parameter extraction failed: {e}"

    if action in ("buy", "sell"):
        if speak:
            speak(f"Executing {action} order for {volume} lots on {symbol}.")

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            mt5.shutdown()
            return f"Symbol {symbol} not found in MetaTrader."

        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                mt5.shutdown()
                return f"Symbol {symbol} select failed."

        order_type = mt5.ORDER_TYPE_BUY if action == "buy" else mt5.ORDER_TYPE_SELL

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            mt5.shutdown()
            return f"Could not get tick data for {symbol}."

        price = tick.ask if action == "buy" else tick.bid
        point = symbol_info.point

        pip_distance = DEFAULT_SL_TP_PIPS * 10 * point
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
            mt5.shutdown()
            return error

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error = f"Order failed, retcode={result.retcode} ({mt5.last_error()})"
            mt5.shutdown()
            return error

        sl_info = f", SL: {stop_loss}" if stop_loss else ""
        tp_info = f", TP: {take_profit}" if take_profit else ""
        msg = (
            f"Order placed! Ticket: {result.order}, Price: {result.price}, "
            f"Volume: {result.volume}{sl_info}{tp_info}"
        )
        if speak:
            speak("Order successfully executed in the market.")
        with _monitor_lock:
            _MONITORED_TICKETS.add(result.order)
        _ensure_monitor_running()
        mt5.shutdown()
        return msg

    mt5.shutdown()
    return f"Unknown action: {action}. Supported: info, buy, sell."
