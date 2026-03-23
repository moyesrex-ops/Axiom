from core.capabilities import collect_capabilities, format_capability_report
from core.system_context import format_system_context
from memory.memory_manager import save_to_nexus
from memory.runtime_store import (
    log_capability,
    log_event,
    recent_events,
    recent_failures,
    recent_task_runs,
)


def _snapshot_capabilities() -> None:
    caps = collect_capabilities()
    for name, value in caps.items():
        log_capability(name, "available" if value else "unavailable", str(value))


def system_capabilities(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "summary")).strip().lower()
    limit = int(params.get("limit", 8) or 8)

    if action in ("summary", "status"):
        _snapshot_capabilities()
        report = format_capability_report()
        log_event("capabilities", "capability_snapshot", report[:2000])
        try:
            save_to_nexus("Capability Snapshot", report[:2000])
        except Exception:
            pass
        return report

    if action == "context":
        report = format_system_context()
        log_event("capabilities", "system_context", report[:2000])
        return report

    if action == "failures":
        rows = recent_failures(limit=limit)
        if not rows:
            return "No recent failures recorded."
        lines = ["Recent failures"]
        for row in rows:
            lines.append(
                f"- #{row['id']} [{row['tool']}] {row['description'][:80]} | "
                f"resolved={bool(row['resolved'])} | error={row['error'][:120]}"
            )
        return "\n".join(lines)

    if action == "events":
        rows = recent_events(limit=limit)
        if not rows:
            return "No recent runtime events recorded."
        lines = ["Recent runtime events"]
        for row in rows:
            lines.append(
                f"- #{row['id']} [{row['kind']}] {row['topic']}: {row['content'][:120]}"
            )
        return "\n".join(lines)

    if action == "tasks":
        rows = recent_task_runs(limit=limit)
        if not rows:
            return "No recent task checkpoints recorded."
        lines = ["Recent task checkpoints"]
        for row in rows:
            lines.append(
                f"- [{row['task_id']}] {row['status']} | {row['goal'][:90]} | "
                f"updated={row['updated_at']}"
            )
        return "\n".join(lines)

    return "Unknown action. Use summary, context, failures, events, or tasks."
