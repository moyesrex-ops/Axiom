import re
import threading
import time
from collections import defaultdict

from core.runtime_config import load_runtime_config
from memory.runtime_store import (
    log_event,
    recent_events,
    recent_tool_traces,
    search_knowledge_items,
    upsert_knowledge_item,
)


_LEARNING_THREAD: threading.Thread | None = None
_LEARNING_STOP = threading.Event()
_LEARNING_LOCK = threading.Lock()


def _learning_config() -> dict:
    return load_runtime_config().get("learning", {}) or {}


def _goal_class(text: str) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return "general"
    if any(token in normalized for token in ("trade", "market", "forex", "crypto", "mt5", "trading")):
        return "markets"
    if any(token in normalized for token in ("code", "repo", "bug", "test", "build", "website", "app", "deploy")):
        return "coding"
    if any(token in normalized for token in ("screen", "window", "click", "type", "browser", "desktop", "app")):
        return "computer_use"
    if any(token in normalized for token in ("research", "search", "analyze", "find out", "look up", "summarize")):
        return "research"
    return "general"


def _summarize_recommendations(recommendations: dict[str, list[dict]]) -> str:
    lines = []
    for goal_class, rows in recommendations.items():
        if not rows:
            continue
        lines.append(f"[{goal_class}]")
        for row in rows[:3]:
            lines.append(
                f"- {row['tool']}: success={row['success_rate']:.0%}, avg={row['avg_duration_ms']:.0f}ms, samples={row['samples']}"
            )
    return "\n".join(lines).strip()


def run_learning_cycle(limit: int | None = None) -> dict:
    cfg = _learning_config()
    max_traces = int(limit or cfg.get("max_traces_per_cycle", 300) or 300)
    min_traces = int(cfg.get("min_tool_traces", 8) or 8)
    traces = recent_tool_traces(limit=max_traces)

    result = {
        "status": "skipped",
        "trace_count": len(traces),
        "timestamp": time.time(),
        "recommendations": {},
    }
    if len(traces) < min_traces:
        result["reason"] = f"need at least {min_traces} tool traces"
        return result

    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for trace in traces:
        metadata = trace.get("metadata", {}) or {}
        goal = str(metadata.get("goal", "") or metadata.get("description", "") or "").strip()
        group = _goal_class(goal)
        grouped[group][str(trace.get("tool", "") or "unknown").strip()].append(trace)

    recommendations: dict[str, list[dict]] = {}
    for goal_class, tool_groups in grouped.items():
        rows = []
        for tool_name, samples in tool_groups.items():
            if not tool_name:
                continue
            success_count = sum(1 for sample in samples if sample.get("success"))
            avg_duration_ms = sum(float(sample.get("duration_ms", 0.0) or 0.0) for sample in samples) / max(len(samples), 1)
            rows.append(
                {
                    "tool": tool_name,
                    "samples": len(samples),
                    "success_rate": success_count / max(len(samples), 1),
                    "avg_duration_ms": avg_duration_ms,
                }
            )
        rows.sort(key=lambda row: (row["success_rate"], row["samples"], -row["avg_duration_ms"]), reverse=True)
        recommendations[goal_class] = rows[:5]

    summary = _summarize_recommendations(recommendations)
    result["recommendations"] = recommendations
    result["summary"] = summary
    result["status"] = "completed"

    if summary and bool(cfg.get("save_recommendations_to_memory", True)):
        for goal_class, rows in recommendations.items():
            if not rows:
                continue
            content_lines = [
                f"Observed class: {goal_class}",
                "Preferred tools from recent execution traces:",
            ]
            for row in rows[:3]:
                content_lines.append(
                    f"- {row['tool']} | success_rate={row['success_rate']:.0%} | avg_duration_ms={row['avg_duration_ms']:.0f} | samples={row['samples']}"
                )
            upsert_knowledge_item(
                kind="learning",
                title=f"Routing Insight: {goal_class}",
                content="\n".join(content_lines),
                source="tool_traces",
                metadata={"goal_class": goal_class, "samples": sum(item["samples"] for item in rows)},
            )

    log_event(
        "learning",
        "cycle_completed",
        summary[:2000] if summary else "No recommendations generated.",
        metadata={"trace_count": len(traces), "goal_classes": list(recommendations.keys())},
    )
    return result


def format_learning_status(limit: int = 5) -> str:
    cfg = _learning_config()
    items = search_knowledge_items("Routing Insight learning", limit=max(int(limit), 1))
    learning_events = [row for row in recent_events(limit=max(int(limit) * 4, 12), kind="learning") if row.get("topic") == "cycle_completed"]
    lines = [
        "[LEARNING STATUS]",
        f"- Enabled: {'yes' if cfg.get('enabled', True) else 'no'}",
        f"- Auto-run: {'yes' if cfg.get('auto_run', True) else 'no'}",
        f"- Interval seconds: {int(cfg.get('interval_seconds', 1800) or 1800)}",
        f"- Minimum traces per cycle: {int(cfg.get('min_tool_traces', 8) or 8)}",
        f"- Recent learning cycles: {len(learning_events)}",
    ]
    if items:
        lines.append("- Latest routing insights:")
        for item in items[: max(int(limit), 1)]:
            title = str(item.get("title", "untitled") or "untitled")
            content = str(item.get("content", "") or "").strip().splitlines()
            preview = content[1] if len(content) > 1 else (content[0] if content else "")
            lines.append(f"  {title} -> {preview[:120]}")
    else:
        lines.append("- No routing insights saved yet.")
    return "\n".join(lines)


def _learning_loop(log_func=None) -> None:
    cfg = _learning_config()
    interval_seconds = max(float(cfg.get("interval_seconds", 1800) or 1800), 60.0)
    while not _LEARNING_STOP.is_set():
        try:
            report = run_learning_cycle()
            if callable(log_func):
                log_func(f"[LEARNING] {report.get('status', 'unknown')}: {report.get('summary', report.get('reason', ''))[:240]}")
        except Exception as exc:
            log_event("learning", "cycle_error", str(exc)[:1000])
            if callable(log_func):
                log_func(f"[LEARNING] error: {exc}")
        _LEARNING_STOP.wait(interval_seconds)


def start_learning_daemon(log_func=None) -> bool:
    cfg = _learning_config()
    if not bool(cfg.get("enabled", True)) or not bool(cfg.get("auto_run", True)):
        return False

    global _LEARNING_THREAD
    with _LEARNING_LOCK:
        if _LEARNING_THREAD is not None and _LEARNING_THREAD.is_alive():
            return True
        _LEARNING_STOP.clear()
        _LEARNING_THREAD = threading.Thread(
            target=_learning_loop,
            kwargs={"log_func": log_func},
            daemon=True,
            name="AxiomLearningDaemon",
        )
        _LEARNING_THREAD.start()
        log_event("learning", "daemon_started", "Learning daemon started.")
        return True


def stop_learning_daemon(timeout: float = 5.0) -> None:
    global _LEARNING_THREAD
    with _LEARNING_LOCK:
        if _LEARNING_THREAD is None:
            return
        _LEARNING_STOP.set()
        _LEARNING_THREAD.join(timeout=max(float(timeout), 0.0))
        _LEARNING_THREAD = None
        log_event("learning", "daemon_stopped", "Learning daemon stopped.")
