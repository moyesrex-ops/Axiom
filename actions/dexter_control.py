from core.dexter_bridge import (
    collect_dexter_status,
    configure_dexter,
    dexter_launch_instructions,
    format_dexter_status,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def dexter_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_dexter_status()
        log_event("integration", "dexter_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["dexter_path"] = params.get("repo_path")
        if not updates:
            return format_dexter_status()
        cfg = configure_dexter(updates)
        message = f"Dexter configuration updated: {cfg.get('agent_library', {})}"
        log_event("integration", "dexter_configure", message[:2000], metadata=updates)
        save_to_nexus("Dexter Config", message[:2000], kind="integration", source="runtime.config")
        return "Dexter configuration updated."

    if action == "launch_instructions":
        report = dexter_launch_instructions()
        log_event("integration", "dexter_launch_instructions", report[:2000])
        return report

    status = collect_dexter_status()
    return (
        "Unknown action. Use status, configure, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
