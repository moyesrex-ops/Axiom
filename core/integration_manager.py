from core.automaton_bridge import collect_automaton_status, start_automaton_runtime
from core.lightpanda_bridge import collect_lightpanda_status, start_lightpanda_backend
from core.mirofish_bridge import collect_mirofish_status, start_mirofish_backend
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

    if not messages:
        line = "[INTEGRATION] No external integrations were configured for boot-time startup."
        messages.append(line)
        _emit(log_func, line)
        log_event("integration", "boot_none", line[:2000])

    return messages
