from core.paperclip_bridge import (
    collect_paperclip_status,
    configure_paperclip,
    format_paperclip_status,
    paperclip_launch_instructions,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def paperclip_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_paperclip_status()
        log_event("integration", "paperclip_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        for field in ("repo_path", "api_url", "auto_start"):
            if field in params and params.get(field) not in (None, ""):
                updates[field] = params.get(field)
        if not updates:
            return format_paperclip_status()
        cfg = configure_paperclip(updates)
        message = f"Paperclip configuration updated: {cfg.get('paperclip', {})}"
        log_event("integration", "paperclip_configure", message[:2000], metadata=updates)
        save_to_nexus("Paperclip Config", message[:2000], kind="integration", source="runtime.config")
        return "Paperclip configuration updated."

    if action == "launch_instructions":
        report = paperclip_launch_instructions()
        log_event("integration", "paperclip_launch_instructions", report[:2000])
        return report

    status = collect_paperclip_status()
    return (
        "Unknown action. Use status, configure, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
