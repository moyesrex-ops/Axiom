from core.lossless_claw_bridge import (
    collect_lossless_claw_status,
    configure_lossless_claw,
    format_lossless_claw_status,
    lossless_claw_launch_instructions,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def lossless_claw_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_lossless_claw_status()
        log_event("integration", "lossless_claw_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        for field in ("repo_path", "database_path"):
            if field in params and params.get(field) not in (None, ""):
                updates[field] = params.get(field)
        if not updates:
            return format_lossless_claw_status()
        cfg = configure_lossless_claw(updates)
        message = f"lossless-claw configuration updated: {cfg.get('lossless_claw', {})}"
        log_event("integration", "lossless_claw_configure", message[:2000], metadata=updates)
        save_to_nexus("lossless-claw Config", message[:2000], kind="integration", source="runtime.config")
        return "lossless-claw configuration updated."

    if action == "launch_instructions":
        report = lossless_claw_launch_instructions()
        log_event("integration", "lossless_claw_launch_instructions", report[:2000])
        return report

    status = collect_lossless_claw_status()
    return (
        "Unknown action. Use status, configure, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
