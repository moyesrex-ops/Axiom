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
    "live": {
        "enable_context_window_compression": True,
        "rotation_lead_seconds": 4.0,
        "idle_rotate_window_ms": 900,
        "rapid_reconnect_seconds": 0.75,
        "error_reconnect_seconds": 3.0,
    },
    "audio": {
        "target_input_rms": 4200.0,
        "max_input_gain": 6.2,
        "interrupt": {
            "min_rms": 850.0,
            "ambient_multiplier": 3.35,
            "playback_multiplier": 0.34,
            "min_speech_band_ratio": 0.42,
            "min_zero_crossing_ratio": 0.015,
            "max_zero_crossing_ratio": 0.24,
            "onset_multiplier": 1.12,
            "required_speech_frames": 3,
            "history_frames": 4,
            "ambient_alpha": 0.08,
            "playback_alpha": 0.28,
            "speaker_guard_ms": 120,
            "speaker_guard_min_rms": 360.0,
            "speaker_guard_ambient_multiplier": 2.2,
            "speaker_guard_playback_multiplier": 0.16,
        },
    },
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
    "gemini_native": {
        "enabled": True,
        "enable_live_google_search": True,
        "search_model": "",
        "planning_model": "",
        "reflection_model": "",
        "router_model": "",
        "url_context_model": "",
        "code_execution_model": "",
        "maps_model": "",
        "file_search_model": "",
        "allow_file_search_uploads": False,
        "file_search_max_files": 8,
        "url_context_max_urls": 6,
    },
    "routing": {
        "prefer_local_classifier": True,
        "local_provider": "ollama",
        "local_endpoint": "http://127.0.0.1:11434",
        "local_model": "qwen2.5:7b-instruct",
        "classifier_timeout_seconds": 5.0,
        "simple_request_max_words": 18,
    },
    "learning": {
        "enabled": True,
        "auto_run": True,
        "interval_seconds": 1800,
        "min_tool_traces": 8,
        "max_traces_per_cycle": 300,
        "save_recommendations_to_memory": True,
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
    "crucix": {
        "repo_path": "",
        "api_url": "http://127.0.0.1:3117",
        "auto_start": False,
    },
    "computer_use": {
        "confirm_physical_actions": False,
        "default_verify_seconds": 1.2,
    },
    "skill_library": {
        "enabled": True,
        "everything_claude_code_path": "",
        "superpowers_path": "",
        "planning_with_files_path": "",
        "last30days_skill_path": "",
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
        "openmanus_path": "",
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
