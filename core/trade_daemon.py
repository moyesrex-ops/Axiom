from __future__ import annotations

import re
import threading
import time
from copy import deepcopy
from datetime import date, datetime

from actions.mt5_trading_agent import get_mt5_account_snapshot, list_mt5_symbols
from actions.tradingagents_control import tradingagents_control
from core.runtime_config import load_runtime_config, update_runtime_config
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event, recent_events


_STATE_LOCK = threading.RLock()
_CYCLE_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
_WAKE_EVENT = threading.Event()
_SYMBOL_ACTIVITY: dict[str, dict] = {}
_LOG_FUNC = None

_STATE = {
    "running": False,
    "started_at": "",
    "stopped_at": "",
    "thread_name": "",
    "cycle_count": 0,
    "cycles_without_trade": 0,
    "last_cycle_started_at": "",
    "last_cycle_completed_at": "",
    "last_cycle_summary": "",
    "last_error": "",
    "last_trade_report": "",
    "last_trade_at": "",
    "last_trade_symbols": [],
    "last_checked_symbols": [],
    "last_decisions": [],
    "market_watch_count": 0,
    "symbol_cache_updated_at": "",
    "open_positions_count": 0,
    "floating_pl": 0.0,
    "cursor": 0,
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _trade_daemon_config() -> dict:
    return load_runtime_config().get("trade_daemon", {}) or {}


def _cfg_int(name: str, default: int) -> int:
    value = _trade_daemon_config().get(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _cfg_float(name: str, default: float) -> float:
    value = _trade_daemon_config().get(name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _emit_log(message: str) -> None:
    if callable(_LOG_FUNC):
        try:
            _LOG_FUNC(message)
        except Exception:
            pass


def _set_state(**updates) -> None:
    with _STATE_LOCK:
        _STATE.update(updates)


def _state_snapshot() -> dict:
    with _STATE_LOCK:
        return deepcopy(_STATE)


def _extract_report_signal(report: str) -> dict:
    text = str(report or "").strip()
    action_match = re.search(r"Derived action:\s*([A-Za-z_]+)", text, flags=re.IGNORECASE)
    confidence_match = re.search(r"Confidence:\s*([0-9]+(?:\.[0-9]+)?)%", text, flags=re.IGNORECASE)
    mt5_result_match = re.search(r"MT5 result:\s*(.+)", text, flags=re.IGNORECASE)
    return {
        "action": str(action_match.group(1)).strip().lower() if action_match else "",
        "confidence": float(confidence_match.group(1)) if confidence_match else None,
        "blocked": "Execution blocked:" in text,
        "placed": "Order placed!" in text or "MT5 result: Order placed!" in text,
        "mt5_result": str(mt5_result_match.group(1)).strip() if mt5_result_match else "",
        "report": text,
    }


def _notify_telegram(message: str, *, important: bool = False) -> None:
    cfg = _trade_daemon_config()
    if not bool(cfg.get("telegram_push_updates", True)):
        return
    if not important and not bool(cfg.get("telegram_push_non_trade_cycles", False)):
        return
    try:
        from core.telegram_bridge import broadcast_bridge_message

        broadcast_bridge_message(message)
    except Exception:
        pass


def _configured_groups() -> list[str]:
    raw = _trade_daemon_config().get("allowed_groups", []) or []
    return [str(item).strip().lower() for item in raw if str(item).strip()]


def _configured_preferred_symbols() -> list[str]:
    raw = _trade_daemon_config().get("preferred_symbols", []) or []
    return [str(item).strip().upper() for item in raw if str(item).strip()]


def _filter_symbol_rows(rows: list[dict]) -> list[dict]:
    groups = _configured_groups()
    preferred = _configured_preferred_symbols()
    filtered = list(rows or [])
    if groups:
        filtered = [row for row in filtered if str(row.get("group", "") or "").strip().lower() in groups]
    if not preferred:
        return filtered
    by_symbol = {str(row.get("symbol", "")).strip().upper(): row for row in filtered}
    prioritized = [by_symbol[symbol] for symbol in preferred if symbol in by_symbol]
    remainder = [row for row in filtered if str(row.get("symbol", "")).strip().upper() not in preferred]
    return prioritized + remainder


def _symbol_is_on_cooldown(symbol: str, now_ts: float) -> bool:
    record = dict(_SYMBOL_ACTIVITY.get(symbol, {}) or {})
    if not record:
        return False
    if record.get("last_trade_ts"):
        cooldown = max(0, _cfg_int("trade_cooldown_seconds", 3600))
        return (now_ts - float(record.get("last_trade_ts", 0.0) or 0.0)) < cooldown
    cooldown = max(0, _cfg_int("analysis_cooldown_seconds", 900))
    return (now_ts - float(record.get("last_attempt_ts", 0.0) or 0.0)) < cooldown


def _select_cycle_symbols(rows: list[dict], open_symbols: set[str]) -> list[dict]:
    ordered = _filter_symbol_rows(rows)
    if not ordered:
        return []

    now_ts = time.time()
    max_symbols = max(1, _cfg_int("max_symbols_per_cycle", 4))

    with _STATE_LOCK:
        cursor = int(_STATE.get("cursor", 0) or 0)

    rotated = ordered[cursor:] + ordered[:cursor]
    selected = []
    for row in rotated:
        symbol = str(row.get("symbol", "") or "").strip().upper()
        if not symbol or symbol in open_symbols:
            continue
        if _symbol_is_on_cooldown(symbol, now_ts):
            continue
        selected.append(row)
        if len(selected) >= max_symbols:
            break

    advance = min(max_symbols, len(ordered))
    with _STATE_LOCK:
        _STATE["cursor"] = (cursor + max(1, advance)) % max(len(ordered), 1)
    return selected


def _record_symbol_attempt(symbol: str, *, traded: bool) -> None:
    now_ts = time.time()
    record = dict(_SYMBOL_ACTIVITY.get(symbol, {}) or {})
    record["last_attempt_ts"] = now_ts
    record["last_attempt_at"] = _now_iso()
    if traded:
        record["last_trade_ts"] = now_ts
        record["last_trade_at"] = record["last_attempt_at"]
    _SYMBOL_ACTIVITY[symbol] = record


def _volume_for_cycle() -> float:
    trading_cfg = load_runtime_config().get("trading", {}) or {}
    default_volume = _cfg_float("default_volume", 0.01)
    hard_cap = float(trading_cfg.get("max_order_volume", 0.10) or 0.10)
    return round(min(default_volume, hard_cap), 2)


def _build_trade_request(symbol: str) -> dict:
    cfg = _trade_daemon_config()
    request = {
        "action": "execute_mt5",
        "ticker": symbol,
        "symbol": symbol,
        "trade_date": date.today().isoformat(),
        "volume": _volume_for_cycle(),
        "confirm": True,
        "dry_run": False,
        "min_confidence": _cfg_int("min_confidence", 45),
        "max_volume": _volume_for_cycle(),
        "allowed_symbols": [symbol],
        "timeout": _cfg_int("analysis_timeout_seconds", 900),
        "max_debate_rounds": _cfg_int("max_debate_rounds", 1),
        "max_risk_discuss_rounds": _cfg_int("max_risk_discuss_rounds", 1),
    }
    provider = str(cfg.get("provider", "") or "").strip()
    deep_model = str(cfg.get("deep_model", "") or "").strip()
    quick_model = str(cfg.get("quick_model", "") or "").strip()
    analysts = cfg.get("analysts", []) or []
    if provider:
        request["provider"] = provider
    if deep_model:
        request["deep_model"] = deep_model
    if quick_model:
        request["quick_model"] = quick_model
    if analysts:
        request["analysts"] = analysts
    return request


def _cycle_summary(checked_symbols: list[str], placed_signals: list[dict], decision_rows: list[dict], open_positions: int) -> str:
    if placed_signals:
        actions = ", ".join(f"{row['symbol']} {row['action']}" for row in placed_signals)
        return (
            f"Trade daemon cycle placed {len(placed_signals)} trade(s): {actions}. "
            f"Checked {len(checked_symbols)} symbol(s) with {open_positions} open position(s) already on account."
        )
    if not checked_symbols:
        return f"Trade daemon cycle skipped new entries. Open positions: {open_positions}. No eligible MT5 symbols were available."
    if decision_rows:
        compact = ", ".join(
            f"{row['symbol']}={row['action'] or 'hold'}"
            + (f"({row['confidence']:.0f}%)" if row.get("confidence") is not None else "")
            for row in decision_rows[:4]
        )
        return (
            f"Trade daemon cycle checked {len(checked_symbols)} symbol(s) with no new order placed. "
            f"Latest reads: {compact}."
        )
    return f"Trade daemon cycle checked {len(checked_symbols)} symbol(s) with no new order placed."


def run_trade_daemon_cycle(*, manual: bool = False) -> str:
    if not _CYCLE_LOCK.acquire(blocking=False):
        return "Trade daemon cycle skipped because another cycle is already running."

    try:
        started_at = _now_iso()
        _set_state(last_cycle_started_at=started_at, last_error="")
        cfg = _trade_daemon_config()
        if not bool(cfg.get("enabled", True)):
            message = "Trade daemon is disabled in runtime config."
            _set_state(last_cycle_summary=message, last_cycle_completed_at=_now_iso())
            return message

        symbol_payload = list_mt5_symbols(
            only_visible=bool(cfg.get("use_market_watch_only", True)),
            limit=0,
        )
        if not symbol_payload.get("ok"):
            message = str(symbol_payload.get("message", "Failed to load MT5 symbol universe."))
            _set_state(last_error=message, last_cycle_summary=message, last_cycle_completed_at=_now_iso())
            log_event("trading", "trade_daemon_cycle_failed", message[:2000])
            return message

        symbol_rows = list(symbol_payload.get("symbols", []) or [])
        account = get_mt5_account_snapshot()
        if not account.get("ok"):
            message = str(account.get("message", "Failed to inspect MT5 account state."))
            _set_state(
                market_watch_count=len(symbol_rows),
                symbol_cache_updated_at=_now_iso(),
                last_error=message,
                last_cycle_summary=message,
                last_cycle_completed_at=_now_iso(),
            )
            log_event("trading", "trade_daemon_cycle_failed", message[:2000])
            return message

        positions = list(account.get("positions", []) or [])
        open_symbols = {str(position.get("symbol", "") or "").strip().upper() for position in positions}
        max_open_positions = max(1, _cfg_int("max_open_positions", 5))
        available_slots = max(0, max_open_positions - len(positions))
        checked_symbols: list[str] = []
        placed_signals: list[dict] = []
        decision_rows: list[dict] = []

        _set_state(
            market_watch_count=len(symbol_rows),
            symbol_cache_updated_at=_now_iso(),
            open_positions_count=len(positions),
            floating_pl=float(account.get("floating_pl", 0.0) or 0.0),
        )

        if available_slots <= 0:
            message = (
                f"Trade daemon cycle skipped new entries because the account already has "
                f"{len(positions)} open position(s), meeting max_open_positions={max_open_positions}."
            )
            _set_state(
                cycle_count=int(_state_snapshot().get("cycle_count", 0) or 0) + 1,
                cycles_without_trade=int(_state_snapshot().get("cycles_without_trade", 0) or 0) + 1,
                last_checked_symbols=[],
                last_decisions=[],
                last_cycle_summary=message,
                last_cycle_completed_at=_now_iso(),
            )
            log_event("trading", "trade_daemon_cycle", message[:2000], metadata={"open_positions": len(positions)})
            return message

        selected = _select_cycle_symbols(symbol_rows, open_symbols)
        max_new_trades = min(
            available_slots,
            max(1, _cfg_int("max_new_trades_per_cycle", 2)),
        )

        for row in selected:
            if len(placed_signals) >= max_new_trades:
                break
            symbol = str(row.get("symbol", "") or "").strip().upper()
            if not symbol:
                continue
            checked_symbols.append(symbol)
            report = tradingagents_control(_build_trade_request(symbol))
            signal = _extract_report_signal(report)
            signal["symbol"] = symbol
            decision_rows.append(
                {
                    "symbol": symbol,
                    "action": signal.get("action", ""),
                    "confidence": signal.get("confidence"),
                    "placed": signal.get("placed", False),
                }
            )
            _record_symbol_attempt(symbol, traded=bool(signal.get("placed")))
            if signal.get("placed"):
                placed_signals.append(signal)
                _set_state(last_trade_report=report, last_trade_at=_now_iso())
                log_event(
                    "trading",
                    "trade_daemon_trade",
                    report[:2000],
                    metadata={"symbol": symbol, "action": signal.get("action", ""), "manual": manual},
                )
                _notify_telegram(
                    f"AXIOM trade daemon placed {signal.get('action', 'a')} trade on {symbol}.",
                    important=True,
                )
            elif signal.get("mt5_result"):
                log_event(
                    "trading",
                    "trade_daemon_decision",
                    report[:2000],
                    metadata={
                        "symbol": symbol,
                        "action": signal.get("action", ""),
                        "blocked": bool(signal.get("blocked")),
                        "manual": manual,
                    },
                )

        summary = _cycle_summary(checked_symbols, placed_signals, decision_rows, len(positions))
        prior = _state_snapshot()
        cycles_without_trade = 0 if placed_signals else int(prior.get("cycles_without_trade", 0) or 0) + 1
        last_trade_symbols = [row["symbol"] for row in placed_signals]
        _set_state(
            cycle_count=int(prior.get("cycle_count", 0) or 0) + 1,
            cycles_without_trade=cycles_without_trade,
            last_checked_symbols=checked_symbols,
            last_trade_symbols=last_trade_symbols,
            last_decisions=decision_rows[-8:],
            last_cycle_summary=summary,
            last_cycle_completed_at=_now_iso(),
        )
        log_event(
            "trading",
            "trade_daemon_cycle",
            summary[:2000],
            metadata={
                "checked_symbols": checked_symbols,
                "placed_count": len(placed_signals),
                "manual": manual,
                "open_positions": len(positions),
            },
        )
        try:
            save_to_nexus(
                "Trade Daemon Cycle",
                summary[:2000],
                kind="trading",
                source="trade_daemon",
                metadata={"placed_count": len(placed_signals), "checked_symbols": checked_symbols[:8]},
            )
        except Exception:
            pass
        if placed_signals or manual:
            _notify_telegram(summary, important=bool(placed_signals))
        return summary
    except Exception as error:
        message = f"Trade daemon cycle failed: {error}"
        _set_state(last_error=message, last_cycle_summary=message, last_cycle_completed_at=_now_iso())
        log_event("trading", "trade_daemon_cycle_failed", message[:2000])
        _notify_telegram(message, important=True)
        return message
    finally:
        _CYCLE_LOCK.release()


def _loop() -> None:
    while not _STOP_EVENT.is_set():
        run_trade_daemon_cycle(manual=False)
        if _STOP_EVENT.is_set():
            break
        interval = max(15, _cfg_int("cycle_interval_seconds", 180))
        _WAKE_EVENT.wait(timeout=interval)
        _WAKE_EVENT.clear()

    _set_state(running=False, stopped_at=_now_iso())


def collect_trade_daemon_status() -> dict:
    cfg = _trade_daemon_config()
    snapshot = _state_snapshot()
    if not snapshot.get("last_cycle_summary") and not snapshot.get("cycle_count"):
        try:
            rows = recent_events(limit=20, kind="trading")
        except Exception:
            rows = []
        daemon_rows = [row for row in rows if str(row.get("topic", "") or "").startswith("trade_daemon")]
        cycle_rows = [row for row in daemon_rows if row.get("topic") == "trade_daemon_cycle"]
        trade_rows = [row for row in daemon_rows if row.get("topic") == "trade_daemon_trade"]
        failed_rows = [row for row in daemon_rows if row.get("topic") == "trade_daemon_cycle_failed"]
        if cycle_rows:
            latest = cycle_rows[0]
            snapshot["cycle_count"] = len(cycle_rows)
            snapshot["last_cycle_summary"] = str(latest.get("content", "") or "")
            snapshot["last_cycle_completed_at"] = str(latest.get("created_at", "") or "")
        if trade_rows:
            latest_trade = trade_rows[0]
            snapshot["last_trade_report"] = str(latest_trade.get("content", "") or "")
            snapshot["last_trade_at"] = str(latest_trade.get("created_at", "") or "")
        if failed_rows and not snapshot.get("last_error"):
            snapshot["last_error"] = str(failed_rows[0].get("content", "") or "")
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "auto_start": bool(cfg.get("auto_start", True)),
        "running": bool(snapshot.get("running", False)),
        "cycle_interval_seconds": _cfg_int("cycle_interval_seconds", 180),
        "max_symbols_per_cycle": _cfg_int("max_symbols_per_cycle", 4),
        "max_new_trades_per_cycle": _cfg_int("max_new_trades_per_cycle", 2),
        "max_open_positions": _cfg_int("max_open_positions", 5),
        "default_volume": _cfg_float("default_volume", 0.01),
        "min_confidence": _cfg_int("min_confidence", 45),
        "allowed_groups": [str(item) for item in (cfg.get("allowed_groups", []) or []) if str(item).strip()],
        **snapshot,
    }


def format_trade_daemon_status() -> str:
    status = collect_trade_daemon_status()
    lines = [
        "[TRADE DAEMON]",
        f"Enabled: {'yes' if status['enabled'] else 'no'}",
        f"Running: {'yes' if status['running'] else 'no'}",
        f"Auto-start: {'yes' if status['auto_start'] else 'no'}",
        f"Cycle interval: {status['cycle_interval_seconds']}s",
        f"Universe limit per cycle: {status['max_symbols_per_cycle']}",
        f"Max new trades per cycle: {status['max_new_trades_per_cycle']}",
        f"Max open positions: {status['max_open_positions']}",
        f"Default volume: {status['default_volume']:.2f}",
        f"Minimum confidence: {status['min_confidence']}%",
        f"Allowed groups: {', '.join(status['allowed_groups']) if status['allowed_groups'] else 'all visible MT5 groups'}",
        f"Market Watch symbols cached: {status.get('market_watch_count', 0)}",
        f"Open positions last seen: {status.get('open_positions_count', 0)}",
        f"Floating P/L last seen: {float(status.get('floating_pl', 0.0) or 0.0):.2f}",
        f"Cycles completed: {status.get('cycle_count', 0)}",
        f"Cycles without trade: {status.get('cycles_without_trade', 0)}",
    ]
    if status.get("started_at"):
        lines.append(f"Started at: {status['started_at']}")
    if status.get("last_cycle_started_at"):
        lines.append(f"Last cycle start: {status['last_cycle_started_at']}")
    if status.get("last_cycle_completed_at"):
        lines.append(f"Last cycle end: {status['last_cycle_completed_at']}")
    if status.get("last_trade_at"):
        lines.append(f"Last trade at: {status['last_trade_at']}")
    if status.get("last_trade_symbols"):
        lines.append(f"Last trade symbols: {', '.join(status['last_trade_symbols'])}")
    if status.get("last_checked_symbols"):
        lines.append(f"Last checked symbols: {', '.join(status['last_checked_symbols'])}")
    if status.get("last_decisions"):
        compact = ", ".join(
            f"{row.get('symbol', '')}:{row.get('action', '') or 'hold'}"
            + (f"({float(row.get('confidence')):.0f}%)" if row.get("confidence") is not None else "")
            for row in list(status.get("last_decisions", []) or [])[:6]
        )
        lines.append(f"Recent decisions: {compact}")
    if status.get("last_cycle_summary"):
        lines.append(f"Last summary: {status['last_cycle_summary']}")
    if status.get("last_error"):
        lines.append(f"Last error: {status['last_error']}")
    return "\n".join(lines)


def configure_trade_daemon(updates: dict | None = None) -> dict:
    return update_runtime_config({"trade_daemon": updates or {}})


def start_trade_daemon(*, log_func=None, force: bool = False) -> str:
    global _THREAD, _LOG_FUNC
    cfg = _trade_daemon_config()
    if not bool(cfg.get("enabled", True)) and not force:
        return "Trade daemon is disabled in runtime config."

    with _STATE_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return "Trade daemon is already running."
        _LOG_FUNC = log_func or _LOG_FUNC
        _STOP_EVENT.clear()
        _WAKE_EVENT.clear()
        started_at = _now_iso()
        _STATE.update(
            {
                "running": True,
                "started_at": started_at,
                "stopped_at": "",
                "thread_name": "AxiomTradeDaemon",
                "last_error": "",
            }
        )
        _THREAD = threading.Thread(target=_loop, daemon=True, name="AxiomTradeDaemon")
        _THREAD.start()

    message = "Trade daemon started."
    log_event("trading", "trade_daemon_started", message, metadata={"auto_start": bool(cfg.get("auto_start", True))})
    _emit_log("[TRADE] Persistent trade daemon started.")
    _notify_telegram("AXIOM trade daemon is live and rotating across MT5 Market Watch symbols.", important=True)
    return message


def stop_trade_daemon(timeout: float = 5.0) -> str:
    global _THREAD
    with _STATE_LOCK:
        thread = _THREAD
        if thread is None:
            return "Trade daemon is not running."
        _STOP_EVENT.set()
        _WAKE_EVENT.set()

    if thread.is_alive():
        thread.join(timeout=max(float(timeout or 0.0), 0.5))

    with _STATE_LOCK:
        if _THREAD is thread and not thread.is_alive():
            _THREAD = None
        _STATE["running"] = False
        _STATE["stopped_at"] = _now_iso()

    message = "Trade daemon stopped."
    log_event("trading", "trade_daemon_stopped", message)
    _emit_log("[TRADE] Persistent trade daemon stopped.")
    _notify_telegram("AXIOM trade daemon has been stopped.", important=True)
    return message


def trigger_trade_daemon_cycle() -> str:
    with _STATE_LOCK:
        thread = _THREAD
        running = thread is not None and thread.is_alive()
    if running:
        _WAKE_EVENT.set()
        log_event("trading", "trade_daemon_wake", "Immediate cycle requested.")
        return "Trade daemon wake requested. The next cycle will run immediately."
    return run_trade_daemon_cycle(manual=True)
