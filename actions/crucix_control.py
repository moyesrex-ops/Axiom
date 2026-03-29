import json

from core.crucix_bridge import (
    collect_crucix_status,
    configure_crucix,
    crucix_launch_instructions,
    format_crucix_status,
    start_crucix_backend,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def crucix_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_crucix_status()
        log_event("integration", "crucix_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["repo_path"] = str(params.get("repo_path")).strip()
        if "api_url" in params and params.get("api_url") not in (None, ""):
            updates["api_url"] = str(params.get("api_url")).strip()
        if "auto_start" in params:
            updates["auto_start"] = bool(params.get("auto_start"))
        if not updates:
            return format_crucix_status()

        cfg = configure_crucix(updates)
        message = f"Crucix configuration updated: {json.dumps(cfg.get('crucix', {}), ensure_ascii=False)}"
        log_event("integration", "crucix_configure", message[:2000], metadata=updates)
        save_to_nexus("Crucix Config", message[:2000], kind="integration", source="runtime.config")
        return "Crucix configuration updated."

    if action == "brief":
        status = collect_crucix_status()
        lines = [
            "[CRUCIX BRIEF]",
            f"- Reachable: {'yes' if status.get('reachable') else 'no'}",
            f"- Last sweep: {status.get('last_sweep') or 'unknown'}",
            f"- Sources OK / failed: {status.get('sources_ok', 0)} / {status.get('sources_failed', 0)}",
            f"- Idea count: {status.get('idea_count', 0)}",
        ]
        top_ideas = status.get("top_ideas", []) or []
        if top_ideas:
            lines.append(f"- Top ideas: {', '.join(top_ideas)}")
        if status.get("dashboard_data_preview"):
            lines.append(f"- Data preview: {status['dashboard_data_preview']}")
        report = "\n".join(lines)
        log_event("integration", "crucix_brief", report[:2000])
        return report

    if action == "ideas":
        status = collect_crucix_status()
        ideas = status.get("top_ideas", []) or []
        if not ideas:
            return "Crucix does not have any surfaced ideas yet."
        report = "[CRUCIX IDEAS]\n" + "\n".join(f"- {idea}" for idea in ideas)
        log_event("integration", "crucix_ideas", report[:2000])
        return report

    if action == "start":
        result = start_crucix_backend(timeout=float(params.get("timeout", 12.0) or 12.0))
        message = str(result.get("message", "Crucix launch attempted.")).strip()
        log_event("integration", "crucix_start", message[:2000], metadata=result)
        lines = [message]
        if result.get("server_url"):
            lines.append(f"Server URL: {result['server_url']}")
        if result.get("log_path"):
            lines.append(f"Log path: {result['log_path']}")
        return "\n".join(lines)

    if action == "launch_instructions":
        report = crucix_launch_instructions()
        log_event("integration", "crucix_launch_instructions", report[:2000])
        return report

    return "Unknown action. Use status, configure, brief, ideas, start, or launch_instructions."
