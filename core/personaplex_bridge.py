from pathlib import Path

from core.capabilities import collect_capabilities
from core.runtime_config import load_runtime_config, update_runtime_config


DEFAULT_PERSONAPLEX_TEXT_PROMPT = (
    "You enjoy having a good conversation. You are AXIOM, a witty and highly "
    "capable operator who speaks naturally, stays interruptible, and keeps a "
    "clear personality without losing technical precision."
)


def configure_personaplex(updates: dict) -> dict:
    payload = {"personaplex": updates or {}}
    return update_runtime_config(payload)


def personaplex_status_report() -> str:
    caps = collect_capabilities()
    cfg = load_runtime_config().get("personaplex", {})
    lines = [
        "PersonaPlex integration",
        f"Enabled: {'yes' if caps['personaplex_enabled'] else 'no'}",
        f"Repo path: {caps['personaplex_path'] or 'not found'}",
        f"Server URL: {caps['personaplex_server_url'] or 'not configured'}",
        f"Server reachable: {'yes' if caps['personaplex_server_reachable'] else 'no'}",
        f"CPU offload: {'yes' if cfg.get('cpu_offload') else 'no'}",
        f"Auto-start: {'yes' if cfg.get('auto_start') else 'no'}",
        f"Text prompt: {str(cfg.get('text_prompt') or DEFAULT_PERSONAPLEX_TEXT_PROMPT)[:180]}",
    ]
    return "\n".join(lines)


def personaplex_launch_instructions() -> str:
    cfg = load_runtime_config().get("personaplex", {})
    repo_path = str(cfg.get("repo_path", "") or collect_capabilities().get("personaplex_path", ""))
    if not repo_path:
        return (
            "PersonaPlex repo path is not configured. Set it with persona_control "
            "action='configure' and repo_path='C:/path/to/personaplex'."
        )

    cpu_flag = " --cpu-offload" if cfg.get("cpu_offload") else ""
    repo = Path(repo_path)
    command = (
        f"Set-Location '{repo}'; "
        "$ssl = Join-Path $env:TEMP 'personaplex-ssl'; "
        "New-Item -ItemType Directory -Force $ssl | Out-Null; "
        f"python -m moshi.server --ssl $ssl{cpu_flag}"
    )
    return (
        "Launch PersonaPlex from PowerShell with:\n"
        f"{command}\n\n"
        "Prereqs: install the repo, accept the NVIDIA model license on Hugging Face, "
        "set HF_TOKEN, and use localhost:8998 or the configured server URL."
    )
