from core.lightpanda_bridge import (
    collect_lightpanda_status,
    configure_lightpanda,
    format_lightpanda_status,
    lightpanda_launch_instructions,
    start_lightpanda_backend,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def lightpanda_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        report = format_lightpanda_status()
        log_event("integration", "lightpanda_status", report[:2000])
        return report

    if action == "endpoint":
        status = collect_lightpanda_status()
        return (
            f"Configured endpoint: {status['endpoint']}\n"
            f"Resolved websocket endpoint: {status['ws_endpoint']}\n"
            f"Reachable: {'yes' if status['reachable'] else 'no'}"
        )

    if action == "configure":
        updates = {}
        if "backend" in params and params.get("backend") not in (None, ""):
            updates["backend"] = str(params.get("backend")).strip().lower()
        if "endpoint" in params and params.get("endpoint") not in (None, ""):
            updates["lightpanda_endpoint"] = params.get("endpoint")
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["lightpanda_repo_path"] = params.get("repo_path")
        if "auto_connect" in params:
            updates["lightpanda_auto_connect"] = bool(params.get("auto_connect"))
        if "auto_start" in params:
            updates["lightpanda_auto_start"] = bool(params.get("auto_start"))
        if not updates:
            return format_lightpanda_status()

        cfg = configure_lightpanda(updates)
        message = f"Lightpanda browser configuration updated: {cfg.get('browser', {})}"
        log_event("integration", "lightpanda_configure", message[:2000], metadata=updates)
        save_to_nexus("Lightpanda Config", message[:2000], kind="integration", source="runtime.config")
        return "Lightpanda browser configuration updated."

    if action == "launch_instructions":
        report = lightpanda_launch_instructions()
        log_event("integration", "lightpanda_launch_instructions", report[:2000])
        return report

    if action == "start":
        result = start_lightpanda_backend(timeout=float(params.get("timeout", 12.0) or 12.0))
        message = str(result.get("message", "Lightpanda launch attempted.")).strip()
        log_event("integration", "lightpanda_start", message[:2000], metadata=result)
        lines = [message]
        if result.get("endpoint"):
            lines.append(f"Endpoint: {result['endpoint']}")
        if result.get("ws_endpoint"):
            lines.append(f"WebSocket endpoint: {result['ws_endpoint']}")
        if result.get("log_path"):
            lines.append(f"Log path: {result['log_path']}")
        if result.get("log_excerpt"):
            lines.append(f"Log excerpt: {result['log_excerpt']}")
        return "\n".join(lines)

    return "Unknown action. Use status, endpoint, configure, start, or launch_instructions."
