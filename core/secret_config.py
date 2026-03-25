import json
import os
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def load_api_config() -> dict:
    try:
        raw = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def get_secret(name: str, env_names: list[str] | None = None, default: str = "") -> str:
    for env_name in env_names or []:
        value = str(os.getenv(env_name, "") or "").strip()
        if value:
            return value

    value = load_api_config().get(name, default)
    return str(value or default).strip()


def get_gemini_api_key(extra_env_names: list[str] | None = None, default: str = "") -> str:
    env_names = ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
    for env_name in extra_env_names or []:
        env_name = str(env_name or "").strip()
        if env_name and env_name not in env_names:
            env_names.append(env_name)
    return get_secret("gemini_api_key", env_names=env_names, default=default)
