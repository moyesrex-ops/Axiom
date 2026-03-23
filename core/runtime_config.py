import json
import sys
from copy import deepcopy
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
RUNTIME_CONFIG_PATH = CONFIG_DIR / "runtime.json"

DEFAULT_RUNTIME_CONFIG = {
    "voice_name": "Charon",
    "voice_backend": "gemini_live",
    "live_model": "models/gemini-2.5-flash-native-audio-preview-12-2025",
    "text_models": {
        "default": "gemini-2.5-flash",
        "fast": "gemini-2.5-flash-lite",
        "reasoning": "gemini-2.5-pro",
    },
    "personaplex": {
        "enabled": False,
        "server_url": "ws://127.0.0.1:8998/api/chat",
        "text_prompt": (
            "You enjoy having a good conversation. You are AXIOM, a sharp and "
            "technically capable AI operator with natural conversational rhythm."
        ),
        "voice_prompt": "",
        "repo_path": "",
        "auto_start": False,
        "cpu_offload": False,
    },
    "integrations": {
        "mirofish_path": "",
        "automaton_path": "",
        "personaplex_path": "",
    },
    "channels": {
        "telegram": {
            "enabled": False,
            "allowed_chat_ids": [],
            "poll_seconds": 1.5,
            "queue_plain_messages": True,
            "startup_prompt_enabled": True,
        }
    },
}


def _merge_dicts(base: dict, updates: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_runtime_config() -> dict:
    if not RUNTIME_CONFIG_PATH.exists():
        return deepcopy(DEFAULT_RUNTIME_CONFIG)

    try:
        raw = json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return deepcopy(DEFAULT_RUNTIME_CONFIG)
        return _merge_dicts(DEFAULT_RUNTIME_CONFIG, raw)
    except Exception:
        return deepcopy(DEFAULT_RUNTIME_CONFIG)


def save_runtime_config(config: dict) -> dict:
    merged = _merge_dicts(DEFAULT_RUNTIME_CONFIG, config or {})
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return merged


def update_runtime_config(updates: dict) -> dict:
    current = load_runtime_config()
    merged = _merge_dicts(current, updates or {})
    return save_runtime_config(merged)


def get_voice_name(default: str = "Charon") -> str:
    return str(load_runtime_config().get("voice_name", default) or default)
