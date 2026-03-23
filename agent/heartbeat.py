import asyncio
import json
from pathlib import Path

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

def get_base_dir():
    import sys
    if getattr(sys, "frozen", False): return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key():
    config_path = get_base_dir() / "config" / "api_keys.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]
    except Exception:
        return ""

class HeartbeatDaemon:
    """
    A relentless background daemon inspired by Sovereign Automaton architecture.
    Wakes up every N seconds continuously, checking open trades and scanning the horizon.
    If a trade is fundamentally broken, it will override and close it independently.
    """
    def __init__(self, speak_func, log_func):
        self.speak = speak_func
        self.log = log_func
        self.interval = 300  # Check every 5 minutes
        self.is_running = True

    async def start(self):
        self.log("[HEARTBEAT] Daemon fully initialized. Watching background markets.")
        while self.is_running:
            await asyncio.sleep(self.interval)
            await self._pulse()

    async def _pulse(self):
        if mt5 is None: return
        try:
            # We don't initialize here to avoid locking; we assume MT5 logic handles its own state
            # but for safety, we just check if it's responsive.
            info = mt5.terminal_info()
            if info is None: return
            
            positions = mt5.positions_get()
            if not positions:
                return
                
            self.log(f"[HEARTBEAT] Evaluating {len(positions)} active market positions...")
            
            pos_data = []
            for p in positions:
                tick = mt5.symbol_info_tick(p.symbol)
                if tick is None: continue
                current_price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
                pos_data.append(f"Ticket:{p.ticket} | Symbol:{p.symbol} | Type:{'BUY' if p.type==mt5.ORDER_TYPE_BUY else 'SELL'} | Open:{p.price_open} | Cur:{current_price} | PnL:{p.profit}")

            if not pos_data: return
            context = "\n".join(pos_data)

            import google.generativeai as genai
            genai.configure(api_key=_get_api_key())
            model = genai.GenerativeModel("gemini-3.0-flash")
            
            prompt = f"""
            [SENTINEL CORE: AUTOMATED RISK OVERRIDE]
            You are the Axiom Background Heartbeat Daemon.
            Your task is CAPITOL PROTECTION. Analyze these active trades:
            
            {context}
            
            RISK ASSESSMENT CRITERIA:
            - If PnL is deeply negative and structure has broken = CLOSE.
            - If PnL is at extreme profit and structure is hitting resistance = CLOSE.
            
            TASK: Output a JSON array of their Ticket numbers to close.
            If all positions are safe, output [].
            
            STRICT OUTPUT: RETURN THE JSON ARRAY ONLY. NO EXPLANATION. NO MARKDOWN.
            """
            
            response = await asyncio.to_thread(model.generate_content, prompt)
            text = response.text.strip()
            text = text.replace("```json", "").replace("```", "").strip()
            
            # Very strict parse
            if not text.startswith("["): return
            tickets_to_close = json.loads(text)
            
            for t in tickets_to_close:
                for p in positions:
                    if p.ticket == t:
                        self.log(f"[HEARTBEAT] Executing autonomous capital protection on ticket {t}")
                        if self.speak:
                            self.speak("Heartbeat daemon triggered. Autonomously terminating an open position to secure capital structure.")
                        
                        tick = mt5.symbol_info_tick(p.symbol)
                        price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
                        action_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                        
                        req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": p.symbol,
                            "volume": p.volume,
                            "type": action_type,
                            "position": p.ticket,
                            "price": price,
                            "deviation": 20,
                            "magic": 234000,
                            "comment": "Daemon Auto-Close",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            # Evolve!
                            try:
                                from memory.trading_soul import reflect_on_trade
                                reflect_on_trade(p.symbol, p.profit, "Heartbeat daemon automatically closed trade due to risk logic.")
                            except Exception as er:
                                self.log(f"Soul reflection error: {er}")
                                
        except Exception as e:
            self.log(f"[HEARTBEAT] Pulse encountered turbulence: {e}")
