from core.symphony_bridge import (
    collect_symphony_status,
    configure_symphony,
    format_symphony_status,
    symphony_launch_instructions,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def symphony_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_symphony_status()
        log_event("integration", "symphony_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        for field in ("repo_path", "workflow_path"):
            if field in params and params.get(field) not in (None, ""):
                updates[field] = params.get(field)
        if not updates:
            return format_symphony_status()
        cfg = configure_symphony(updates)
        message = f"Symphony configuration updated: {cfg.get('symphony', {})}"
        log_event("integration", "symphony_configure", message[:2000], metadata=updates)
        save_to_nexus("Symphony Config", message[:2000], kind="integration", source="runtime.config")
        return "Symphony configuration updated."

    if action == "launch_instructions":
        report = symphony_launch_instructions()
        log_event("integration", "symphony_launch_instructions", report[:2000])
        return report

    status = collect_symphony_status()
    return (
        "Unknown action. Use status, configure, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
