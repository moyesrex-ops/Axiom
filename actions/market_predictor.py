import json
import asyncio
from typing import Optional, Dict, Any
from datetime import date


def get_api_key() -> str:
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

def _load_soul_lessons() -> str:
    """Load past trading lessons from the soul to avoid repeating mistakes."""
    import sys
    from pathlib import Path
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    soul_path = base / "memory" / "trading_soul.json"
    if not soul_path.exists():
        return "No past lessons recorded yet."
    try:
        with open(soul_path, "r", encoding="utf-8") as f:
            soul_data = json.load(f)
        lessons = soul_data.get("lessons_learned", [])
        if lessons:
            return "\n".join([f"- {l['lesson']}" for l in lessons[-10:]])
    except Exception:
        pass
    return "No past lessons recorded yet."


def _mirofish_context_block(asset: str, source_mode: str = "auto") -> tuple[str, dict]:
    mode = str(source_mode or "auto").strip().lower()
    if mode == "axiom":
        return "", {"used": False, "reason": "disabled"}

    try:
        from core.mirofish_bridge import get_mirofish_market_context
    except Exception as error:
        return "", {"used": False, "reason": f"bridge_unavailable: {error}"}

    context = get_mirofish_market_context(asset=asset, limit=6)
    if not context.get("available"):
        return "", {"used": False, "reason": "repo_not_found"}

    lines = [
        f"MiroFish repo detected at: {context.get('repo_path', '')}",
        f"MiroFish backend reachable: {'yes' if context.get('backend_reachable') else 'no'}",
    ]
    if context.get("seed_description"):
        lines.append(f"Seed scenario: {context['seed_description']}")

    profiles = context.get("matching_profiles", []) or []
    if profiles:
        lines.append("Relevant MiroFish seed personas:")
        for row in profiles[:6]:
            lines.append(
                f"- {row.get('entity_name', 'unknown')} [{row.get('platform', 'seed')}]: "
                f"bio={row.get('bio', '')} | interests={row.get('interests', '')}"
            )

    posts = context.get("matching_posts", []) or []
    if posts:
        lines.append("Relevant MiroFish seed posts:")
        for row in posts[:3]:
            lines.append(f"- {row.get('content', '')}")

    report_excerpt = str(context.get("report_excerpt", "")).strip()
    if report_excerpt:
        lines.append("Latest matching MiroFish report excerpt:")
        lines.append(report_excerpt)

    return "\n".join(line for line in lines if line.strip()), {
        "used": True,
        "backend_reachable": bool(context.get("backend_reachable")),
        "profiles_used": len(profiles),
        "has_report_excerpt": bool(report_excerpt),
    }


def _crucix_context_block(asset: str, source_mode: str = "auto") -> tuple[str, dict]:
    mode = str(source_mode or "auto").strip().lower()
    if mode != "auto":
        return "", {"used": False, "reason": f"source_mode={mode}"}

    try:
        from core.crucix_bridge import get_crucix_market_context
    except Exception as error:
        return "", {"used": False, "reason": f"bridge_unavailable: {error}"}

    context = get_crucix_market_context(asset=asset, limit=6)
    if not context.get("available"):
        return "", {"used": False, "reason": "repo_or_api_unavailable"}

    lines = [
        f"Crucix API reachable: {'yes' if context.get('reachable') else 'no'}",
        f"Crucix last sweep: {context.get('last_sweep') or 'unknown'}",
        (
            f"Crucix LLM layer: {'enabled' if context.get('llm_enabled') else 'disabled'}"
            + (f" ({context.get('llm_provider')})" if context.get("llm_provider") else "")
        ),
    ]
    for row in context.get("market_snapshot", [])[:4]:
        lines.append(f"- Snapshot: {row}")
    if context.get("relevant_headlines"):
        lines.append("Relevant Crucix headlines:")
        for row in context["relevant_headlines"][:4]:
            lines.append(f"- {row.get('headline', '')}")
    if context.get("urgent_posts"):
        lines.append("Relevant Crucix urgent posts:")
        for row in context["urgent_posts"][:2]:
            lines.append(f"- {row.get('text', '')}")
    if context.get("ideas"):
        lines.append("Relevant Crucix live ideas:")
        for row in context["ideas"][:2]:
            title = str(row.get("title", "") or row.get("summary", "")).strip()
            if title:
                lines.append(f"- {title}")

    return "\n".join(line for line in lines if str(line).strip()), {
        "used": True,
        "reachable": bool(context.get("reachable")),
        "headline_count": len(context.get("relevant_headlines", []) or []),
        "idea_count": len(context.get("ideas", []) or []),
    }


def _run_swarm_agent(model, role: str, asset: str, soul_lessons: str, context: str) -> str:
    """
    Run a single swarm agent with a specific role and return its analysis.
    Each agent is a specialized analyst role with a constrained viewpoint.
    """
    role_prompts = {
        "macro_economist": f"""
You are a Macro-Economist AI agent participating in a market swarm debate for {asset}.
Your sole focus: macroeconomic forces — interest rates, inflation, GDP trends, geopolitical risk,
central bank policy, and global capital flows.

SOUL LESSONS (don't repeat past mistakes): {soul_lessons}
ADDITIONAL CONTEXT: {context}

Provide your macroeconomic verdict on {asset}: Bull/Bear/Neutral with specific reasoning.
Be brutally honest. End with: VERDICT: [BULL/BEAR/NEUTRAL] | CONFIDENCE: [0-100]%
""",
        "technical_analyst": f"""
You are a Technical Analyst AI agent participating in a market swarm debate for {asset}.
Your sole focus: price action, chart structure, momentum indicators (RSI, MACD), 
support/resistance levels, volume analysis, and candlestick patterns.

SOUL LESSONS (don't repeat past mistakes): {soul_lessons}
ADDITIONAL CONTEXT: {context}

Provide your technical verdict on {asset}: Bull/Bear/Neutral with specific structural reasoning.
End with: VERDICT: [BULL/BEAR/NEUTRAL] | CONFIDENCE: [0-100]%
""",
        "risk_manager": f"""
You are a Risk Manager AI agent participating in a market swarm debate for {asset}.
Your sole focus: volatility assessment, drawdown risk, position sizing logic, liquidity concerns,
black swan scenarios, and whether the risk/reward ratio justifies a trade.

SOUL LESSONS (don't repeat past mistakes): {soul_lessons}
ADDITIONAL CONTEXT: {context}

Provide your risk assessment for {asset}. Should we trade it, or is the risk too high?
End with: VERDICT: [PROCEED/AVOID/CAUTION] | CONFIDENCE: [0-100]%
""",
    }

    prompt = role_prompts.get(role, "")
    if not prompt:
        return f"Unknown role: {role}"

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Agent '{role}' failed: {e}"


def _synthesize_debate(model, asset: str, macro: str, technical: str, risk: str) -> str:
    """Have a final synthesis pass that reads all three agent outputs and produces a consensus."""
    prompt = f"""
[SWARM CONSENSUS ENGINE — AXIOM]
Three expert AI agents have analysed {asset}. Your job is to synthesise their debate
into a final, actionable intelligence report.

─── MACRO-ECONOMIST REPORT ───
{macro}

─── TECHNICAL ANALYST REPORT ───
{technical}

─── RISK MANAGER REPORT ───
{risk}

SYNTHESIS INSTRUCTIONS:
1. Identify agreement and conflict between agents.
2. Weigh each perspective (macro: 30%, technical: 40%, risk: 30%).
3. Produce a FINAL VERDICT: Bullish / Bearish / Neutral.
4. Provide an OVERALL CONFIDENCE score (0-100%).
5. State a clear suggested action: BUY | SELL | HOLD | AVOID.
6. List the top 3 risks that could invalidate this thesis.

Output as a clean, professional diagnostic. Be direct and avoid AI filler.
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Synthesis failed: {e}"


def predict_market(parameters: dict = None, player=None, speak=None) -> str:
    """
    MiroFish-style Swarm Market Predictor.

    Spawns three AI analyst agents (Macro-Economist, Technical Analyst, Risk Manager)
    that each independently analyse the asset and then debate to reach a consensus.
    All results are automatically persisted to AXIOM's durable memory archive.
    """
    params = parameters or {}
    asset = params.get("asset", "EURUSD")
    context = params.get("context", "")
    source_mode = str(params.get("source", "auto") or "auto").strip().lower()
    trade_date = str(params.get("trade_date", "") or date.today().isoformat()).strip()

    def _bg_predict():
        if source_mode == "tradingagents":
            try:
                from core.tradingagents_bridge import (
                    format_tradingagents_analysis,
                    run_tradingagents_analysis,
                )

                if speak:
                    speak(f"Running TradingAgents market analysis for {asset}.")

                result = run_tradingagents_analysis(
                    {
                        "ticker": str(asset or "").strip().upper(),
                        "trade_date": trade_date,
                        "provider": params.get("provider", ""),
                        "deep_model": params.get("deep_model", ""),
                        "quick_model": params.get("quick_model", ""),
                        "analysts": params.get("analysts", ""),
                        "max_debate_rounds": params.get("max_debate_rounds", 1),
                        "max_risk_discuss_rounds": params.get("max_risk_discuss_rounds", 1),
                        "timeout": params.get("timeout", 1800),
                    }
                )
                report = format_tradingagents_analysis(result)
                try:
                    from memory.memory_manager import save_to_nexus

                    save_to_nexus(
                        f"TradingAgents Prediction: {asset}",
                        report[:4000],
                        kind="research",
                        source="tradingagents.predict_market",
                        metadata={"asset": asset, "trade_date": trade_date, "ok": bool(result.get("ok"))},
                    )
                except Exception:
                    pass
                if speak:
                    speak(f"TradingAgents market analysis complete for {asset}.")
                elif player and hasattr(player, "write_log"):
                    player.write_log(f"TradingAgents Predict:\n{report}")
                return
            except Exception as error:
                msg = f"TradingAgents market analysis failed: {error}"
                if speak: speak(msg)
                return

        mirofish_context, mirofish_meta = _mirofish_context_block(asset, source_mode=source_mode)
        crucix_context, crucix_meta = _crucix_context_block(asset, source_mode=source_mode)
        combined_context = str(context or "").strip()
        if mirofish_context:
            combined_context = (
                f"{combined_context}\n\n[MiroFish External Context]\n{mirofish_context}"
                if combined_context
                else f"[MiroFish External Context]\n{mirofish_context}"
            )
        if crucix_context:
            combined_context = (
                f"{combined_context}\n\n[Crucix Live Context]\n{crucix_context}"
                if combined_context
                else f"[Crucix Live Context]\n{crucix_context}"
            )

        if speak:
            if mirofish_meta.get("used") and crucix_meta.get("used"):
                speak(f"Initiating swarm prediction sequence for {asset}. I'm layering live Crucix and MiroFish context into the debate.")
            elif mirofish_meta.get("used"):
                speak(f"Initiating swarm prediction sequence for {asset}. I'm layering MiroFish context into the debate.")
            elif crucix_meta.get("used"):
                speak(f"Initiating swarm prediction sequence for {asset}. I'm layering Crucix live context into the debate.")
            else:
                speak(f"Initiating swarm prediction sequence for {asset}. Three agents are now debating.")

        try:
            import google.generativeai as genai
            genai.configure(api_key=get_api_key())
            model = genai.GenerativeModel("gemini-2.5-pro")

            soul_lessons = _load_soul_lessons()

            print(f"[SwarmPredictor] 🤖 Spawning Macro-Economist agent for {asset}...")
            macro_report = _run_swarm_agent(model, "macro_economist", asset, soul_lessons, combined_context)

            print(f"[SwarmPredictor] 📈 Spawning Technical Analyst agent for {asset}...")
            technical_report = _run_swarm_agent(model, "technical_analyst", asset, soul_lessons, combined_context)

            print(f"[SwarmPredictor] ⚖️ Spawning Risk Manager agent for {asset}...")
            risk_report = _run_swarm_agent(model, "risk_manager", asset, soul_lessons, combined_context)

            print(f"[SwarmPredictor] 🔮 Synthesising swarm consensus for {asset}...")
            consensus = _synthesize_debate(model, asset, macro_report, technical_report, risk_report)

            full_report = (
                f"═══ AXIOM SWARM PREDICTION: {asset} ═══\n\n"
                f"{'── CRUCIX LIVE CONTEXT ──\\n' + crucix_context + '\\n\\n' if crucix_context else ''}"
                f"{'── EXTERNAL MIROFISH CONTEXT ──\\n' + mirofish_context + '\\n\\n' if mirofish_context else ''}"
                f"── MACRO-ECONOMIST ──\n{macro_report}\n\n"
                f"── TECHNICAL ANALYST ──\n{technical_report}\n\n"
                f"── RISK MANAGER ──\n{risk_report}\n\n"
                f"══ SWARM CONSENSUS ══\n{consensus}"
            )

            if speak:
                speak(f"Swarm debate complete for {asset}. Consensus achieved. Full diagnostic is now in the logs.")
            elif player and hasattr(player, "write_log"):
                player.write_log(full_report)

            # Persist to durable memory for later retrieval
            try:
                from memory.memory_manager import save_to_nexus
                save_to_nexus(
                    f"Swarm Prediction: {asset}",
                    consensus[:2000],
                    kind="research",
                    source="axiom.predict_market",
                    metadata={"asset": asset, "source_mode": source_mode, **mirofish_meta, **crucix_meta},
                )
                save_to_nexus(f"Macro Report: {asset}", macro_report[:1000], kind="research", source="axiom.predict_market")
                save_to_nexus(f"Technical Report: {asset}", technical_report[:1000], kind="research", source="axiom.predict_market")
                save_to_nexus(f"Risk Report: {asset}", risk_report[:1000], kind="research", source="axiom.predict_market")
                if mirofish_context:
                    save_to_nexus(
                        f"MiroFish Context: {asset}",
                        mirofish_context[:2500],
                        kind="research",
                        source="mirofish.seed",
                        metadata={"asset": asset, **mirofish_meta},
                    )
                if crucix_context:
                    save_to_nexus(
                        f"Crucix Context: {asset}",
                        crucix_context[:2500],
                        kind="research",
                        source="crucix.market_context",
                        metadata={"asset": asset, **crucix_meta},
                    )
            except Exception:
                pass

            return

        except Exception as e:
            error_msg = f"Swarm prediction engine failed: {str(e)}"
            if speak:
                speak("My prediction swarm encountered an anomaly.")
            elif player and hasattr(player, "write_log"):
                player.write_log(error_msg)
            return

    import threading
    threading.Thread(target=_bg_predict, daemon=True, name=f"PredictMarket_{asset}").start()
    return f"Market prediction sequence for {asset} started in background. I will notify you when consensus is reached."
