from core.pentagi_bridge import (
    collect_pentagi_status,
    configure_pentagi,
    format_pentagi_status,
    pentagi_launch_instructions,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def pentagi_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_pentagi_status()
        log_event("integration", "pentagi_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["pentagi_path"] = params.get("repo_path")
        if not updates:
            return format_pentagi_status()
        cfg = configure_pentagi(updates)
        message = f"PentAGI configuration updated: {cfg.get('agent_library', {})}"
        log_event("integration", "pentagi_configure", message[:2000], metadata=updates)
        save_to_nexus("PentAGI Config", message[:2000], kind="integration", source="runtime.config")
        return "PentAGI configuration updated."

    if action == "launch_instructions":
        report = pentagi_launch_instructions()
        log_event("integration", "pentagi_launch_instructions", report[:2000])
        return report

    status = collect_pentagi_status()
    return (
        "Unknown action. Use status, configure, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
