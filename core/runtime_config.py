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
RUNTIME_LOCAL_CONFIG_PATH = CONFIG_DIR / "runtime.local.json"

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
        "mirofish_url": "http://127.0.0.1:5001",
        "mirofish_auto_start": False,
        "automaton_path": "",
        "automaton_state_dir": "",
        "automaton_auto_start": False,
        "personaplex_path": "",
    },
    "research": {
        "backend": "auto",
        "vane_url": "",
        "vane_chat_provider": "",
        "vane_chat_model": "",
        "vane_embedding_provider": "",
        "vane_embedding_model": "",
        "deep_search_max_queries": 4,
        "deep_search_results_per_query": 4,
    },
    "browser": {
        "backend": "playwright",
        "lightpanda_endpoint": "http://127.0.0.1:9222",
        "lightpanda_auto_connect": False,
        "lightpanda_auto_start": False,
        "lightpanda_repo_path": "",
        "lightpanda_wsl_binary_path": "",
    },
    "deerflow": {
        "repo_path": "",
        "auto_start": False,
        "url": "http://127.0.0.1:2026",
        "gateway_url": "",
        "langgraph_url": "",
    },
    "paperclip": {
        "repo_path": "",
        "api_url": "http://127.0.0.1:3100",
        "auto_start": False,
    },
    "openfang": {
        "repo_path": "",
        "dashboard_url": "http://127.0.0.1:4200",
        "auto_start": False,
    },
    "symphony": {
        "repo_path": "",
        "workflow_path": "WORKFLOW.md",
    },
    "lossless_claw": {
        "repo_path": "",
        "database_path": "",
    },
    "skill_library": {
        "enabled": True,
        "everything_claude_code_path": "",
        "superpowers_path": "",
        "antigravity_skills_path": "",
        "deerflow_path": "",
        "impeccable_path": "",
        "gstack_path": "",
        "cli_anything_path": "",
        "uncodixfy_path": "",
        "paperclip_path": "",
        "openfang_path": "",
        "local_skills_path": "",
        "search_limit": 8,
    },
    "agent_library": {
        "enabled": True,
        "wshobson_agents_path": "",
        "awesome_subagents_path": "",
        "dexter_path": "",
        "pentagi_path": "",
        "tradingagents_path": "",
        "paperclip_path": "",
        "openfang_path": "",
        "symphony_path": "",
        "lossless_claw_path": "",
        "search_limit": 8,
        "delegate_limit": 3,
        "delegate_model": "",
    },
    "tradingagents": {
        "repo_path": "",
        "provider": "google",
        "deep_think_llm": "",
        "quick_think_llm": "",
        "default_analysts": ["market", "social", "news", "fundamentals"],
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    },
    "research_repos": {
        "autoresearch_path": "",
    },
    "autonomy": {
        "auto_specialists": True,
        "delegate_specialists": True,
        "specialist_task_min_words": 6,
        "specialist_limit": 2,
        "save_task_strategies": True,
        "reuse_task_strategies": True,
        "task_strategy_limit": 2,
    },
    "system_context": {
        "enable_public_ip_lookup": False,
    },
    "channels": {
        "telegram": {
            "enabled": False,
            "allowed_chat_ids": [],
            "poll_seconds": 1.5,
            "queue_plain_messages": True,
            "plain_message_mode": "operator",
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


def _read_config_file(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_config_file(path: Path, payload: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _select_write_path(prefer_local: bool = True) -> Path:
    if prefer_local or RUNTIME_LOCAL_CONFIG_PATH.exists():
        return RUNTIME_LOCAL_CONFIG_PATH
    return RUNTIME_CONFIG_PATH


def load_runtime_config() -> dict:
    merged = deepcopy(DEFAULT_RUNTIME_CONFIG)
    try:
        if RUNTIME_CONFIG_PATH.exists():
            raw = _read_config_file(RUNTIME_CONFIG_PATH)
            if isinstance(raw, dict):
                merged = _merge_dicts(merged, raw)
    except Exception:
        return deepcopy(DEFAULT_RUNTIME_CONFIG)
    try:
        if RUNTIME_LOCAL_CONFIG_PATH.exists():
            raw_local = _read_config_file(RUNTIME_LOCAL_CONFIG_PATH)
            if isinstance(raw_local, dict):
                merged = _merge_dicts(merged, raw_local)
    except Exception:
        pass
    return merged


def save_runtime_config(config: dict, prefer_local: bool = True) -> dict:
    target_path = _select_write_path(prefer_local=prefer_local)
    if target_path == RUNTIME_LOCAL_CONFIG_PATH:
        payload = config or {}
    else:
        payload = _merge_dicts(DEFAULT_RUNTIME_CONFIG, config or {})
    _write_config_file(target_path, payload)
    return load_runtime_config()


def update_runtime_config(updates: dict, prefer_local: bool = True) -> dict:
    target_path = _select_write_path(prefer_local=prefer_local)
    current_target = _read_config_file(target_path)
    merged_target = _merge_dicts(current_target, updates or {})
    _write_config_file(target_path, merged_target)
    return load_runtime_config()


def get_voice_name(default: str = "Charon") -> str:
    return str(load_runtime_config().get("voice_name", default) or default)
