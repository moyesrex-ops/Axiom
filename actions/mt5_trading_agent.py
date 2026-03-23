import time
from typing import Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

def mt5_trading(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = params.get("action", "").lower()
    symbol = params.get("symbol", "EURUSD")
    volume = float(params.get("volume", 0.01))
    magic  = int(params.get("magic", 234000))

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
        res = f"MT5 Connected. Balance: {account_info.balance:.2f}, Equity: {account_info.equity:.2f}, Margin: {account_info.margin:.2f}"
        if speak: speak(res)
        mt5.shutdown()
        return res

    if action in ("buy", "sell"):
        if speak: speak(f"Executing {action} order for {volume} lots on {symbol}.")
        
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
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": magic,
            "comment": "Axiom v3 Auto",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result is None:
            error = f"Order send failed completely. ({mt5.last_error()})"
            mt5.shutdown()
            return error
            
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error = f"Order failed, retcode={result.retcode} ({mt5.last_error()})"
            mt5.shutdown()
            return error
            
        msg = f"Order placed successfully! Ticket: {result.order}, Price: {result.price}, Volume: {result.volume}"
        if speak: speak("Order successfully executed in the market.")
        mt5.shutdown()
        return msg

    mt5.shutdown()
    return f"Unknown action: {action}. Supported: info, buy, sell."
