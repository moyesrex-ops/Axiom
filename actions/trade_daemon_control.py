from core.trade_daemon import (
    collect_trade_daemon_status,
    configure_trade_daemon,
    format_trade_daemon_status,
    start_trade_daemon,
    stop_trade_daemon,
    trigger_trade_daemon_cycle,
)
from memory.runtime_store import log_event


def trade_daemon_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_trade_daemon_status()
        log_event("trading", "trade_daemon_status", report[:2000])
        return report

    if action == "start":
        message = start_trade_daemon(log_func=getattr(player, "write_log", None))
        log_event("trading", "trade_daemon_start_request", message[:500])
        if speak:
            speak(message)
        return message

    if action == "stop":
        message = stop_trade_daemon()
        log_event("trading", "trade_daemon_stop_request", message[:500])
        if speak:
            speak(message)
        return message

    if action in ("run_once", "wake"):
        message = trigger_trade_daemon_cycle()
        log_event("trading", "trade_daemon_run_once", message[:1000])
        if speak:
            speak(message)
        return message

    if action == "configure":
        updates = {}
        for key in (
            "enabled",
            "auto_start",
            "cycle_interval_seconds",
            "max_symbols_per_cycle",
            "max_new_trades_per_cycle",
            "max_open_positions",
            "default_volume",
            "min_confidence",
            "allowed_groups",
            "preferred_symbols",
            "analysis_cooldown_seconds",
            "trade_cooldown_seconds",
            "telegram_push_updates",
            "telegram_push_non_trade_cycles",
            "use_market_watch_only",
            "provider",
            "deep_model",
            "quick_model",
            "analysts",
            "analysis_timeout_seconds",
            "max_debate_rounds",
            "max_risk_discuss_rounds",
        ):
            if key in params and params.get(key) not in (None, ""):
                updates[key] = params.get(key)
        if not updates:
            return format_trade_daemon_status()
        config = configure_trade_daemon(updates)
        trade_config = (config.get("trade_daemon", {}) or {}) if isinstance(config, dict) else {}
        message = f"Trade daemon configuration updated: {trade_config}"
        log_event("trading", "trade_daemon_configure", message[:2000], metadata=updates)
        return message

    if action == "snapshot":
        status = collect_trade_daemon_status()
        log_event("trading", "trade_daemon_snapshot", str(status)[:2000])
        return str(status)

    return "Unknown action. Use status, start, stop, run_once, wake, configure, or snapshot."
