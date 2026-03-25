from core.openfang_bridge import (
    collect_openfang_status,
    configure_openfang,
    format_openfang_status,
    openfang_launch_instructions,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def openfang_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_openfang_status()
        log_event("integration", "openfang_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        for field in ("repo_path", "dashboard_url", "auto_start"):
            if field in params and params.get(field) not in (None, ""):
                updates[field] = params.get(field)
        if not updates:
            return format_openfang_status()
        cfg = configure_openfang(updates)
        message = f"OpenFang configuration updated: {cfg.get('openfang', {})}"
        log_event("integration", "openfang_configure", message[:2000], metadata=updates)
        save_to_nexus("OpenFang Config", message[:2000], kind="integration", source="runtime.config")
        return "OpenFang configuration updated."

    if action == "launch_instructions":
        report = openfang_launch_instructions()
        log_event("integration", "openfang_launch_instructions", report[:2000])
        return report

    status = collect_openfang_status()
    return (
        "Unknown action. Use status, configure, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
