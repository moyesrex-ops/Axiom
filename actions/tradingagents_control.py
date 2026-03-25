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
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


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
        return report

    if action == "launch_instructions":
        report = tradingagents_launch_instructions()
        log_event("integration", "tradingagents_launch_instructions", report[:2000])
        return report

    status = collect_tradingagents_status(limit=limit)
    return (
        "Unknown action. Use status, runs, configure, prepare, analyze, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
