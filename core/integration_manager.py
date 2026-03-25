from core.agent_library import collect_agent_library_status
from core.automaton_bridge import collect_automaton_status, start_automaton_runtime
from core.dexter_bridge import collect_dexter_status
from core.lightpanda_bridge import collect_lightpanda_status, start_lightpanda_backend
from core.mirofish_bridge import collect_mirofish_status, start_mirofish_backend
from core.pentagi_bridge import collect_pentagi_status
from core.runtime_config import load_runtime_config
from memory.runtime_store import log_event


def _emit(log_func, message: str) -> None:
    if callable(log_func):
        try:
            log_func(message)
        except Exception:
            pass


def boot_integrations(log_func=None) -> list[str]:
    runtime = load_runtime_config()
    integrations = runtime.get("integrations", {}) or {}
    messages: list[str] = []

    mirofish_status = collect_mirofish_status(limit=1)
    if integrations.get("mirofish_auto_start", False):
        try:
            result = start_mirofish_backend(timeout=12.0)
        except Exception as exc:
            result = {"started": False, "message": f"MiroFish boot raised an exception: {exc}"}
        msg = str(result.get("message", "MiroFish auto-start attempted.")).strip()
        if result.get("started"):
            line = f"[INTEGRATION] MiroFish: {msg}"
        else:
            line = f"[INTEGRATION] MiroFish blocked: {msg}"
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "mirofish_boot", line[:2000], metadata=result)
    elif mirofish_status.get("repo_path"):
        line = "[INTEGRATION] MiroFish detected. Auto-start is disabled."
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "mirofish_boot_skipped", line[:2000], metadata={"repo_path": mirofish_status.get("repo_path", "")})

    automaton_status = collect_automaton_status()
    if integrations.get("automaton_auto_start", False):
        try:
            result = start_automaton_runtime(timeout=8.0)
        except Exception as exc:
            result = {"started": False, "message": f"Automaton boot raised an exception: {exc}"}
        msg = str(result.get("message", "Automaton auto-start attempted.")).strip()
        if result.get("started"):
            line = f"[INTEGRATION] Automaton: {msg}"
        else:
            line = f"[INTEGRATION] Automaton blocked: {msg}"
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "automaton_boot", line[:2000], metadata=result)
    elif automaton_status.get("repo_path"):
        line = "[INTEGRATION] Automaton detected. Auto-start is disabled."
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "automaton_boot_skipped", line[:2000], metadata={"repo_path": automaton_status.get("repo_path", "")})

    lightpanda_status = collect_lightpanda_status()
    browser_cfg = runtime.get("browser", {}) or {}
    if browser_cfg.get("lightpanda_auto_start", False):
        try:
            result = start_lightpanda_backend(timeout=12.0)
        except Exception as exc:
            result = {"started": False, "message": f"Lightpanda boot raised an exception: {exc}"}
        msg = str(result.get("message", "Lightpanda auto-start attempted.")).strip()
        if result.get("started"):
            line = f"[INTEGRATION] Lightpanda: {msg}"
        else:
            line = f"[INTEGRATION] Lightpanda blocked: {msg}"
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "lightpanda_boot", line[:2000], metadata=result)
    elif lightpanda_status.get("repo_path"):
        line = "[INTEGRATION] Lightpanda detected. Auto-start is disabled."
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "lightpanda_boot_skipped", line[:2000], metadata={"repo_path": lightpanda_status.get("repo_path", "")})

    dexter_status = collect_dexter_status()
    if dexter_status.get("repo_path"):
        line = (
            f"[INTEGRATION] Dexter detected. Bun {'available' if dexter_status.get('bun_available') else 'missing'}."
        )
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "dexter_detected", line[:2000], metadata=dexter_status)

    pentagi_status = collect_pentagi_status()
    if pentagi_status.get("repo_path"):
        if pentagi_status.get("audit_notice_present") and not pentagi_status.get("source_available"):
            line = "[INTEGRATION] PentAGI docs detected. Upstream source is temporarily unavailable during a license audit."
        else:
            line = "[INTEGRATION] PentAGI detected."
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "pentagi_detected", line[:2000], metadata=pentagi_status)

    agent_library = collect_agent_library_status(limit=4)
    if agent_library.get("enabled") and agent_library.get("sources_count", 0):
        line = (
            f"[INTEGRATION] Agent library indexed {agent_library.get('total_agents', 0)} agents "
            f"across {agent_library.get('sources_count', 0)} sources."
        )
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "agent_library_detected", line[:2000], metadata=agent_library)

    if not messages:
        line = "[INTEGRATION] No external integrations were configured for boot-time startup."
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "boot_none", line[:2000])

    return messages
