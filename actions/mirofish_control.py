from core.mirofish_bridge import (
    configure_mirofish,
    format_mirofish_market_context,
    format_mirofish_status,
    list_mirofish_projects,
    list_mirofish_reports,
    list_mirofish_simulations,
    mirofish_launch_instructions,
    start_mirofish_backend,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def mirofish_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    limit = int(params.get("limit", 5) or 5)

    if action == "status":
        return format_mirofish_status(limit=limit)

    if action == "projects":
        rows = list_mirofish_projects(limit=limit)
        if not rows:
            return "No MiroFish projects were found on disk."
        lines = ["MiroFish projects"]
        for row in rows:
            lines.append(
                f"- {row['project_id']} [{row['status']}] "
                f"name={row['name']} graph={row['graph_id'] or 'none'} files={row['files_count']}"
            )
        return "\n".join(lines)

    if action == "simulations":
        rows = list_mirofish_simulations(limit=limit)
        if not rows:
            return "No MiroFish simulations were found on disk."
        lines = ["MiroFish simulations"]
        for row in rows:
            lines.append(
                f"- {row['simulation_id']} [{row['status']}] "
                f"project={row['project_id'] or 'unknown'} round={row['current_round']} "
                f"profiles={row['profiles_count']}"
            )
        return "\n".join(lines)

    if action == "reports":
        rows = list_mirofish_reports(limit=limit)
        if not rows:
            return "No MiroFish reports were found on disk."
        lines = ["MiroFish reports"]
        for row in rows:
            lines.append(
                f"- {row['report_id']} [{row['status']}] "
                f"simulation={row['simulation_id'] or 'unknown'} "
                f"excerpt={row['markdown_excerpt'] or 'n/a'}"
            )
        return "\n".join(lines)

    if action == "market_seed":
        asset = str(params.get("asset", "")).strip() or "market"
        report = format_mirofish_market_context(asset=asset, limit=limit)
        log_event("integration", "mirofish_market_seed", report[:2000], metadata={"asset": asset})
        save_to_nexus(
            f"MiroFish Market Context: {asset}",
            report[:6000],
            kind="research",
            source="mirofish.seed",
            metadata={"asset": asset},
        )
        return report

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["mirofish_path"] = params.get("repo_path")
        if "server_url" in params and params.get("server_url") not in (None, ""):
            updates["mirofish_url"] = params.get("server_url")
        if "auto_start" in params:
            updates["mirofish_auto_start"] = bool(params.get("auto_start"))
        if not updates:
            return format_mirofish_status(limit=limit)
        cfg = configure_mirofish(updates)
        msg = f"MiroFish integration configuration updated: {cfg['integrations']}"
        log_event("integration", "mirofish_configure", msg[:2000])
        save_to_nexus("MiroFish Config", msg[:2000], kind="integration", source="runtime.json")
        return "MiroFish integration configuration updated."

    if action == "start_backend":
        result = start_mirofish_backend()
        msg = str(result.get("message", "MiroFish backend launch attempted.")).strip()
        log_event("integration", "mirofish_start_backend", msg[:2000], metadata=result)
        return (
            f"{msg}\n"
            f"Server URL: {result.get('server_url', '') or 'unknown'}\n"
            f"Log path: {result.get('log_path', '') or 'n/a'}"
        ).strip()

    if action == "launch_instructions":
        return mirofish_launch_instructions()

    return (
        "Unknown action. Use status, projects, simulations, reports, market_seed, "
        "configure, start_backend, or launch_instructions."
    )
