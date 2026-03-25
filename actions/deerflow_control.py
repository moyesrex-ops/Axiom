from core.deerflow_bridge import (
    collect_deerflow_status,
    configure_deerflow,
    deerflow_launch_instructions,
    format_deerflow_status,
    run_deerflow_query,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def deerflow_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    limit = int(params.get("limit", 5) or 5)

    if action == "status":
        report = format_deerflow_status(limit=limit)
        log_event("integration", "deerflow_status", report[:2000])
        return report

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["repo_path"] = params.get("repo_path")
        if "url" in params and params.get("url") not in (None, ""):
            updates["url"] = params.get("url")
        if "gateway_url" in params and params.get("gateway_url") not in (None, ""):
            updates["gateway_url"] = params.get("gateway_url")
        if "langgraph_url" in params and params.get("langgraph_url") not in (None, ""):
            updates["langgraph_url"] = params.get("langgraph_url")
        if not updates:
            return format_deerflow_status(limit=limit)
        cfg = configure_deerflow(updates)
        message = f"DeerFlow configuration updated: {cfg.get('deerflow', {})}"
        log_event("integration", "deerflow_configure", message[:2000], metadata=updates)
        save_to_nexus("DeerFlow Config", message[:2000], kind="integration", source="runtime.config")
        return "DeerFlow configuration updated."

    if action in {"query", "chat", "run"}:
        prompt = str(
            params.get("prompt", "")
            or params.get("query", "")
            or params.get("goal", "")
            or ""
        ).strip()
        if not prompt:
            return "Use action='query' with prompt=<message>."
        if speak:
            speak("Sending this task to DeerFlow.")
        result = run_deerflow_query(
            prompt=prompt,
            mode=str(params.get("mode", "pro") or "pro").strip().lower(),
            thread_id=str(params.get("thread_id", "") or "").strip(),
            timeout=int(params.get("timeout", 240) or 240),
        )
        if not result.get("ok"):
            report = str(result.get("message", "DeerFlow query failed.")).strip()
            log_event("research", "deerflow_query_failed", report[:2000], metadata=result)
            return report
        report = (
            f"DeerFlow response [{result.get('mode', 'pro')}]\n"
            f"Thread ID: {result.get('thread_id', '')}\n"
            f"Run ID: {result.get('run_id', '') or 'n/a'}\n\n"
            f"{str(result.get('response_text', '')).strip()}"
        ).strip()
        log_event("research", "deerflow_query", prompt[:300], metadata=result)
        save_to_nexus(
            f"DeerFlow: {prompt[:60]}",
            report[:6000],
            kind="research",
            source="deerflow.query",
            metadata={"thread_id": result.get("thread_id", ""), "mode": result.get("mode", "pro")},
        )
        return report

    if action == "launch_instructions":
        report = deerflow_launch_instructions()
        log_event("integration", "deerflow_launch_instructions", report[:2000])
        return report

    status = collect_deerflow_status(limit=limit)
    return (
        "Unknown action. Use status, configure, query, or launch_instructions.\n"
        f"Repo detected: {'yes' if status['repo_path'] else 'no'}."
    )
