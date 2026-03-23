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

def _load_soul_context() -> str:
    """Load last 5 lessons from the Trading Soul for OODA reflection."""
    soul_path = get_base_dir() / "memory" / "trading_soul.json"
    if not soul_path.exists():
        return "No past lessons recorded."
    try:
        with open(soul_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        lessons = data.get("lessons_learned", [])
        if lessons:
            return "\n".join([f"- {l['lesson']}" for l in lessons[-5:]])
    except Exception:
        pass
    return "No past lessons recorded."

class HeartbeatDaemon:
    """
    Conway Automaton Event Loop — Sovereign OODA (Observe, Orient, Decide, Act) Daemon.

    Every pulse cycle it:
      1. OBSERVE  — Fetches all market positions via BrokerManager (MT5 + Crypto + any connected exchange).
      2. ORIENT   — Reflects on past lessons from trading_soul.json.
      3. DECIDE   — Runs a Gemini swarm debate to determine whether to HOLD, CLOSE, or flag new trades.
      4. ACT      — Executes autonomous closes via BrokerManager and logs everything to the Nexus Brain.
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
        try:
            # ── OBSERVE ──────────────────────────────────────────────────────
            from core.broker_manager import BrokerManager
            broker = BrokerManager()
            positions = await asyncio.to_thread(broker.get_all_positions)

            if not positions:
                return

            self.log(f"[HEARTBEAT] OBSERVE: {len(positions)} active position(s) detected across all markets.")

            pos_summary = []
            for p in positions:
                pos_summary.append(
                    f"Market:{p['market']} | Symbol:{p['symbol']} | "
                    f"Type:{p['type']} | PnL:{p['unrealized_pnl']:.2f} | "
                    f"Ticket:{p['ticket']} | Volume:{p['volume']}"
                )
            market_state = "\n".join(pos_summary)

            # ── ORIENT ───────────────────────────────────────────────────────
            soul_context = await asyncio.to_thread(_load_soul_context)

            # ── DECIDE ───────────────────────────────────────────────────────
            import google.generativeai as genai
            genai.configure(api_key=_get_api_key())
            model = genai.GenerativeModel("gemini-2.5-flash")

            prompt = f"""
[AXIOM SOVEREIGN OODA LOOP — HEARTBEAT DAEMON]
You are the inner autonomous mind of Axiom, running silently in the background.

── OBSERVE ──
Current open positions across ALL connected markets:
{market_state}

── ORIENT ──
Past trading lessons (do NOT repeat these mistakes):
{soul_context}

── DECIDE ──
You must now decide for each position: HOLD, CLOSE, or MONITOR_CLOSELY.

DECISION CRITERIA:
- CLOSE if: PnL is deeply negative AND market structure has broken, OR PnL is at extreme profit hitting resistance.
- HOLD if: position is within normal volatility and thesis is intact.
- MONITOR_CLOSELY if: position is borderline — not urgent but needs watching.

Think step by step. Consider risk, reward, and momentum.
Then output a JSON object in this EXACT format:
{{
  "decisions": [
    {{"ticket": "TICKET_ID", "action": "HOLD|CLOSE|MONITOR_CLOSELY", "reason": "brief reason"}}
  ],
  "overall_assessment": "one sentence market overview"
}}

STRICT: Output ONLY the JSON. No markdown. No extra text.
"""
            response = await asyncio.to_thread(model.generate_content, prompt)
            text = response.text.strip()
            text = text.replace("```json", "").replace("```", "").strip()

            if not text.startswith("{"):
                return

            decision_data = json.loads(text)
            decisions = decision_data.get("decisions", [])
            overall = decision_data.get("overall_assessment", "")

            if overall:
                self.log(f"[HEARTBEAT] ORIENT: {overall}")

            # ── ACT ──────────────────────────────────────────────────────────
            for decision in decisions:
                ticket = str(decision.get("ticket", ""))
                action = decision.get("action", "HOLD").upper()
                reason = decision.get("reason", "")

                if action == "CLOSE":
                    self.log(f"[HEARTBEAT] ACT: Closing ticket {ticket} — {reason}")
                    if self.speak:
                        self.speak(f"Heartbeat daemon triggered. Autonomously closing a position to protect capital.")

                    success = await asyncio.to_thread(broker.close_position_by_ticket, ticket)

                    # Find position data for soul reflection
                    pos_data = next((p for p in positions if str(p["ticket"]) == ticket), {})
                    pnl = pos_data.get("unrealized_pnl", 0)
                    symbol = pos_data.get("symbol", ticket)

                    if success:
                        self.log(f"[HEARTBEAT] ✅ Position {ticket} closed successfully.")
                        try:
                            from memory.trading_soul import reflect_on_trade
                            reflect_on_trade(symbol, pnl, f"Heartbeat OODA daemon closed trade: {reason}")
                        except Exception as er:
                            self.log(f"[HEARTBEAT] Soul reflection error: {er}")
                    else:
                        self.log(f"[HEARTBEAT] ⚠️ Close attempt for {ticket} failed or not confirmed.")

                    # Always log to Nexus Brain
                    try:
                        from memory.memory_manager import save_to_nexus
                        save_to_nexus(
                            f"Autonomous Close: {symbol}",
                            f"Daemon closed ticket {ticket} | PnL: {pnl} | Reason: {reason}"
                        )
                    except Exception:
                        pass

                elif action == "MONITOR_CLOSELY":
                    self.log(f"[HEARTBEAT] 👁️ Monitoring closely: ticket {ticket} — {reason}")
                    try:
                        from memory.memory_manager import save_to_nexus
                        save_to_nexus(
                            f"Monitor Flag: {ticket}",
                            f"Daemon flagged for close watch | Reason: {reason}"
                        )
                    except Exception:
                        pass

            # Log the full pulse to Nexus Brain
            try:
                from memory.memory_manager import save_to_nexus
                save_to_nexus(
                    "Last Heartbeat Pulse",
                    f"Positions: {len(positions)} | Decisions: {len(decisions)} | {overall}"
                )
            except Exception:
                pass

        except Exception as e:
            self.log(f"[HEARTBEAT] Pulse encountered turbulence: {e}")
