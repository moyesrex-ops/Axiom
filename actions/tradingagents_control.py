import re

from core.tradingagents_bridge import (
    collect_tradingagents_status,
    configure_tradingagents,
    format_tradingagents_analysis,
    format_tradingagents_status,
    list_tradingagents_runs,
    prepare_tradingagents_repo,
    run_tradingagents_analysis,
    tradingagents_launch_instructions,
)
from actions.mt5_trading_agent import mt5_trading
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def _extract_first_number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _classify_trade_action(text: str) -> str:
    normalized = str(text or "").lower()
    if not normalized:
        return ""

    decision_lines = [
        line.strip()
        for line in re.split(r"[\r\n]+", normalized)
        if any(token in line for token in ("decision", "verdict", "action", "trade"))
    ]
    haystacks = decision_lines + [normalized]

    for haystack in haystacks:
        if any(token in haystack for token in (" buy", "buy", " long", "bullish")):
            return "buy"
        if any(token in haystack for token in (" sell", "sell", " short", "bearish")):
            return "sell"
        if any(token in haystack for token in (" avoid", "avoid", " hold", "neutral", "no trade")):
            return "hold"
    return ""


def _build_mt5_handoff(result: dict, params: dict) -> dict:
    signal_text = "\n".join(
        str(result.get(key, "") or "")
        for key in (
            "fusion_summary",
            "fusion_reason",
            "final_trade_decision",
            "decision",
            "trader_investment_plan",
            "investment_plan",
        )
    )
    action = str(result.get("fusion_action", "") or "").strip().lower() or _classify_trade_action(signal_text)
    confidence = result.get("fusion_confidence")
    if confidence in (None, ""):
        confidence = _extract_first_number(r"confidence[^0-9]{0,12}(\d{1,3}(?:\.\d+)?)", signal_text)
    stop_loss = result.get("fusion_stop_loss")
    if stop_loss in (None, ""):
        stop_loss = _extract_first_number(r"(?:stop[- ]?loss|sl)[^0-9]{0,12}(-?\d+(?:\.\d+)?)", signal_text)
    take_profit = result.get("fusion_take_profit")
    if take_profit in (None, ""):
        take_profit = _extract_first_number(r"(?:take[- ]?profit|tp)[^0-9]{0,12}(-?\d+(?:\.\d+)?)", signal_text)

    symbol = str(params.get("symbol", "") or result.get("ticker", "") or "").strip().upper()
    volume = float(params.get("volume", 0.01) or 0.01)
    min_confidence = params.get("min_confidence")
    min_confidence = int(min_confidence) if min_confidence not in (None, "") else None
    max_volume = float(params.get("max_volume", 0.10) or 0.10)
    allowed_symbols = params.get("allowed_symbols", [])
    if isinstance(allowed_symbols, str):
        allowed_symbols = [part.strip().upper() for part in allowed_symbols.split(",") if part.strip()]
    else:
        allowed_symbols = [str(item).strip().upper() for item in (allowed_symbols or []) if str(item).strip()]

    blocked_reasons = []
    if action not in ("buy", "sell"):
        blocked_reasons.append("TradingAgents did not produce a clear BUY or SELL signal.")
    if volume > max_volume:
        blocked_reasons.append(f"Requested volume {volume:.2f} exceeds max_volume {max_volume:.2f}.")
    if allowed_symbols and symbol not in allowed_symbols:
        blocked_reasons.append(f"Symbol {symbol} is outside allowed_symbols.")
    if min_confidence is not None and confidence is not None and confidence < min_confidence:
        blocked_reasons.append(f"Confidence {confidence:.1f}% is below min_confidence {min_confidence}%.")

    return {
        "action": action,
        "symbol": symbol,
        "volume": volume,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "confidence": confidence,
        "confirm": bool(params.get("confirm", False)),
        "dry_run": bool(params.get("dry_run", False)),
        "min_confidence": min_confidence,
        "max_volume": max_volume,
        "allowed_symbols": allowed_symbols,
        "blocked_reasons": blocked_reasons,
    }


def _format_mt5_handoff(result: dict, handoff: dict, execution_result: str = "") -> str:
    lines = [
        f"TradingAgents -> MT5 handoff for {result.get('ticker', '')} @ {result.get('trade_date', '')}",
        f"Derived action: {handoff.get('action') or 'none'}",
        f"MT5 symbol: {handoff.get('symbol', '') or 'n/a'}",
        f"Volume: {handoff.get('volume', 0.0):.2f}",
        (
            f"Confidence: {handoff['confidence']:.1f}%"
            if handoff.get("confidence") is not None
            else "Confidence: not provided by TradingAgents output"
        ),
    ]
    if handoff.get("stop_loss") is not None:
        lines.append(f"Stop loss: {handoff['stop_loss']}")
    if handoff.get("take_profit") is not None:
        lines.append(f"Take profit: {handoff['take_profit']}")
    if handoff.get("blocked_reasons"):
        lines.append("Execution blocked:")
        for reason in handoff["blocked_reasons"]:
            lines.append(f"- {reason}")
    elif not handoff.get("confirm") or handoff.get("dry_run"):
        lines.append("Execution mode: dry run only. No live MT5 order was sent.")
        if not handoff.get("confirm"):
            lines.append("Set confirm=true to allow live execution after reviewing the handoff.")
    else:
        lines.append("Execution mode: live MT5 order requested.")
    if execution_result:
        lines.append(f"MT5 result: {execution_result}")
    if result.get("fusion_summary"):
        lines.append(f"Live context fusion: {result['fusion_summary'][:500]}")
    if result.get("run_file"):
        lines.append(f"TradingAgents run log: {result['run_file']}")
    return "\n".join(lines)


def tradingagents_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    limit = int(params.get("limit", 5) or 5)

    if action == "status":
        report = format_tradingagents_status(limit=limit)
        log_event("integration", "tradingagents_status", report[:2000])
        return report

    if action == "runs":
        rows = list_tradingagents_runs(limit=limit)
        if not rows:
            return "No TradingAgents runs were found on disk."
        lines = ["TradingAgents runs"]
        for row in rows:
            lines.append(
                f"- {row['ticker']} @ {row['trade_date']} | "
                f"decision={row['final_trade_decision'] or 'n/a'} | path={row['path']}"
            )
        return "\n".join(lines)

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["repo_path"] = params.get("repo_path")
        if "provider" in params and params.get("provider") not in (None, ""):
            updates["provider"] = str(params.get("provider")).strip().lower()
        if "deep_model" in params and params.get("deep_model") not in (None, ""):
            updates["deep_think_llm"] = params.get("deep_model")
        if "quick_model" in params and params.get("quick_model") not in (None, ""):
            updates["quick_think_llm"] = params.get("quick_model")
        if "analysts" in params and params.get("analysts") not in (None, ""):
            updates["default_analysts"] = params.get("analysts")
        if "max_debate_rounds" in params and params.get("max_debate_rounds") not in (None, ""):
            updates["max_debate_rounds"] = int(params.get("max_debate_rounds"))
        if "max_risk_discuss_rounds" in params and params.get("max_risk_discuss_rounds") not in (None, ""):
            updates["max_risk_discuss_rounds"] = int(params.get("max_risk_discuss_rounds"))
        if not updates:
            return format_tradingagents_status(limit=limit)
        cfg = configure_tradingagents(updates)
        message = f"TradingAgents configuration updated: {cfg.get('tradingagents', {})}"
        log_event("integration", "tradingagents_configure", message[:2000], metadata=updates)
        save_to_nexus("TradingAgents Config", message[:2000], kind="integration", source="runtime.config")
        return "TradingAgents configuration updated."

    if action == "prepare":
        result = prepare_tradingagents_repo(timeout=int(params.get("timeout", 1800) or 1800))
        message = str(result.get("message", "TradingAgents prepare attempted.")).strip()
        log_event("integration", "tradingagents_prepare", message[:2000], metadata=result)
        lines = [message]
        if result.get("venv_ready") is not None:
            lines.append(f"Sidecar venv ready: {'yes' if result['venv_ready'] else 'no'}")
        if result.get("import_ready") is not None:
            lines.append(f"Package import ready: {'yes' if result['import_ready'] else 'no'}")
        if result.get("output_excerpt"):
            lines.append(f"Output excerpt: {result['output_excerpt']}")
        return "\n".join(lines)

    if action == "analyze":
        ticker = str(params.get("ticker", "") or params.get("asset", "") or "").strip().upper()
        if not ticker:
            return "Use action='analyze' with ticker=<symbol>."
        if speak:
            speak(f"Running TradingAgents analysis for {ticker}.")
        def _bg_analyze():
            try:
                result = run_tradingagents_analysis(params)
                report = format_tradingagents_analysis(result)
                log_event(
                    "research",
                    "tradingagents_analyze",
                    report[:2000],
                    metadata={
                        "ok": bool(result.get("ok")),
                        "ticker": ticker,
                        "trade_date": result.get("trade_date", ""),
                    },
                )
                if result.get("ok"):
                    save_to_nexus(
                        f"TradingAgents Analysis: {ticker}",
                        report[:6000],
                        kind="research",
                        source="tradingagents.analyze",
                        metadata={
                            "ticker": ticker,
                            "trade_date": result.get("trade_date", ""),
                            "provider": result.get("provider", ""),
                        },
                    )
                if speak:
                    speak(f"TradingAgents analysis complete for {ticker}. The decision is {result.get('final_trade_decision', 'HOLD')}.")
                elif player and hasattr(player, "write_log"):
                    player.write_log(f"TradingAgents analysis for {ticker}:\n{report}")
            except Exception as e:
                msg = f"TradingAgents background analysis failed: {e}"
                if speak:
                    speak(msg)
                elif player and hasattr(player, "write_log"):
                    player.write_log(msg)

        import threading
        t = threading.Thread(target=_bg_analyze, daemon=True, name=f"TradingAgents_{ticker}")
        t.start()
        return f"Analyzing {ticker} now. I'll report back when the read is ready."

    if action == "execute_mt5":
        ticker = str(params.get("ticker", "") or params.get("asset", "") or "").strip().upper()
        if not ticker:
            return "Use action='execute_mt5' with ticker=<symbol>."
        if speak:
            speak(f"Running TradingAgents analysis and preparing an MT5 handoff for {ticker}.")

        def _run_execute() -> str:
            result = run_tradingagents_analysis(params)
            if not result.get("ok"):
                report = format_tradingagents_analysis(result)
                log_event("trading", "tradingagents_mt5_handoff_failed", report[:2000], metadata={"ticker": ticker})
                return report

            handoff = _build_mt5_handoff(result, params)
            execution_result = ""

            if not handoff["blocked_reasons"] and handoff["confirm"] and not handoff["dry_run"]:
                execution_result = mt5_trading(
                    {
                        "action": handoff["action"],
                        "symbol": handoff["symbol"],
                        "volume": handoff["volume"],
                        "stop_loss": handoff["stop_loss"],
                        "take_profit": handoff["take_profit"],
                    },
                    player=player,
                    speak=speak,
                )

            report = _format_mt5_handoff(result, handoff, execution_result=execution_result)
            log_event(
                "trading",
                "tradingagents_mt5_handoff",
                report[:2000],
                metadata={
                    "ticker": ticker,
                    "trade_date": result.get("trade_date", ""),
                    "action": handoff.get("action", ""),
                    "symbol": handoff.get("symbol", ""),
                    "confirm": handoff.get("confirm", False),
                    "dry_run": handoff.get("dry_run", False),
                    "blocked": bool(handoff.get("blocked_reasons")),
                },
            )
            save_to_nexus(
                f"TradingAgents MT5 Handoff: {ticker}",
                report[:4000],
                kind="trading",
                source="tradingagents.execute_mt5",
                metadata={
                    "ticker": ticker,
                    "trade_date": result.get("trade_date", ""),
                    "action": handoff.get("action", ""),
                    "symbol": handoff.get("symbol", ""),
                    "confirm": handoff.get("confirm", False),
                },
            )
            return report

        should_background = bool(speak) or bool(player and hasattr(player, "write_log"))
        if not should_background:
            try:
                return _run_execute()
            except Exception as e:
                return f"TradingAgents MT5 execution failed: {e}"

        def _bg_execute():
            try:
                report = _run_execute()
                if speak:
                    if "Execution blocked:" in report:
                        speak(f"TradingAgents completed for {ticker}, but execution was blocked.")
                    elif "MT5 result:" in report:
                        speak(f"TradingAgents MT5 execution complete for {ticker}.")
                    else:
                        speak(f"TradingAgents MT5 evaluation complete for {ticker}, but no trade was forced.")
                elif player and hasattr(player, "write_log"):
                    player.write_log(f"MT5 execution evaluated for {ticker}:\n{report}")
            except Exception as e:
                msg = f"TradingAgents MT5 execution failed: {e}"
                if speak:
                    speak(msg)
                elif player and hasattr(player, "write_log"):
                    player.write_log(msg)

        import threading
        t = threading.Thread(target=_bg_execute, daemon=True, name=f"MT5Handoff_{ticker}")
        t.start()
        return f"Analyzing {ticker} and preparing the MT5 handoff now. I'll report back when it's complete."


    if action == "launch_instructions":
        report = tradingagents_launch_instructions()
        log_event("integration", "tradingagents_launch_instructions", report[:2000])
        return report

    status = collect_tradingagents_status(limit=limit)
    return (
        "Unknown action. Use status, runs, configure, prepare, analyze, execute_mt5, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
