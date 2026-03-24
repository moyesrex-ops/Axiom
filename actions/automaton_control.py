from core.automaton_bridge import (
    automaton_launch_instructions,
    automaton_soul_excerpt,
    configure_automaton,
    format_automaton_memory_snapshot,
    format_automaton_status,
    start_automaton_runtime,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def automaton_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        return format_automaton_status()

    if action in ("memory", "state"):
        report = format_automaton_memory_snapshot()
        log_event("integration", "automaton_memory_snapshot", report[:2000])
        return report

    if action == "soul":
        report = automaton_soul_excerpt(limit=int(params.get("limit", 1600) or 1600))
        log_event("integration", "automaton_soul_excerpt", report[:2000])
        save_to_nexus(
            "Automaton SOUL Snapshot",
            report[:6000],
            kind="integration",
            source="automaton.soul",
        )
        return report

    if action == "configure":
        updates = {}
        if "repo_path" in params and params.get("repo_path") not in (None, ""):
            updates["automaton_path"] = params.get("repo_path")
        if "state_dir" in params and params.get("state_dir") not in (None, ""):
            updates["automaton_state_dir"] = params.get("state_dir")
        if "auto_start" in params:
            updates["automaton_auto_start"] = bool(params.get("auto_start"))
        if not updates:
            return format_automaton_status()
        cfg = configure_automaton(updates)
        msg = f"Automaton integration configuration updated: {cfg['integrations']}"
        log_event("integration", "automaton_configure", msg[:2000])
        save_to_nexus("Automaton Config", msg[:2000], kind="integration", source="runtime.json")
        return "Automaton integration configuration updated."

    if action == "start_runtime":
        result = start_automaton_runtime()
        msg = str(result.get("message", "Automaton launch attempted.")).strip()
        log_event("integration", "automaton_start_runtime", msg[:2000], metadata=result)
        return (
            f"{msg}\n"
            f"Log path: {result.get('log_path', '') or 'n/a'}"
        ).strip()

    if action == "launch_instructions":
        return automaton_launch_instructions()

    return "Unknown action. Use status, memory, state, soul, configure, start_runtime, or launch_instructions."
