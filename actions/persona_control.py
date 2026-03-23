from core.personaplex_bridge import (
    DEFAULT_PERSONAPLEX_TEXT_PROMPT,
    configure_personaplex,
    personaplex_launch_instructions,
    personaplex_status_report,
)
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event


def persona_control(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()

    if action == "status":
        return personaplex_status_report()

    if action == "enable":
        cfg = configure_personaplex(
            {
                "enabled": True,
                "server_url": params.get("server_url", "ws://127.0.0.1:8998/api/chat"),
                "repo_path": params.get("repo_path", ""),
                "text_prompt": params.get("text_prompt", DEFAULT_PERSONAPLEX_TEXT_PROMPT),
                "voice_prompt": params.get("voice_prompt", ""),
                "cpu_offload": bool(params.get("cpu_offload", False)),
                "auto_start": bool(params.get("auto_start", False)),
            }
        )
        msg = (
            "PersonaPlex integration enabled. "
            f"Server URL: {cfg['personaplex']['server_url']}"
        )
        log_event("persona", "personaplex_enable", msg)
        save_to_nexus("PersonaPlex Config", msg)
        return msg

    if action == "disable":
        configure_personaplex({"enabled": False})
        msg = "PersonaPlex integration disabled."
        log_event("persona", "personaplex_disable", msg)
        return msg

    if action == "configure":
        updates = {}
        for field in ("server_url", "repo_path", "text_prompt", "voice_prompt"):
            if field in params and params.get(field) not in (None, ""):
                updates[field] = params.get(field)
        if "cpu_offload" in params:
            updates["cpu_offload"] = bool(params.get("cpu_offload"))
        if "auto_start" in params:
            updates["auto_start"] = bool(params.get("auto_start"))
        if "enabled" in params:
            updates["enabled"] = bool(params.get("enabled"))
        if not updates:
            return personaplex_status_report()
        cfg = configure_personaplex(updates)
        msg = f"PersonaPlex configuration updated: {cfg['personaplex']}"
        log_event("persona", "personaplex_configure", msg[:2000])
        save_to_nexus("PersonaPlex Config", msg[:2000])
        return "PersonaPlex configuration updated."

    if action == "launch_instructions":
        return personaplex_launch_instructions()

    return "Unknown action. Use status, enable, disable, configure, or launch_instructions."
