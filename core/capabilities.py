import importlib.util
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from core.runtime_config import load_runtime_config
from core.secret_config import get_secret


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _path_or_none(value: str) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _first_existing_path(candidates: list[Path]) -> str:
    for candidate in candidates:
        try:
            if candidate is not None and candidate.exists():
                return str(candidate)
        except Exception:
            continue
    return ""


def _parse_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        return host, parsed.port
    if parsed.scheme in ("https", "wss"):
        return host, 443
    return host, 80


def _is_tcp_reachable(url: str, timeout: float = 0.35) -> bool:
    try:
        host, port = _parse_host_port(url)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _api_key_configured() -> bool:
    return bool(get_secret("gemini_api_key", ["GEMINI_API_KEY"]))


def _telegram_token_configured() -> bool:
    return bool(
        get_secret(
            "telegram_bot_token",
            ["AXIOM_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"],
        )
    )


def _integration_candidates() -> dict:
    home = Path.home()
    runtime = load_runtime_config()
    configured = runtime.get("integrations", {})
    personaplex_cfg = runtime.get("personaplex", {})

    return {
        "mirofish": [
            _path_or_none(configured.get("mirofish_path", "")),
            BASE_DIR / "research" / "MiroFish",
            home / "MiroFish",
            home / "MiroFish_upstream",
        ],
        "automaton": [
            _path_or_none(configured.get("automaton_path", "")),
            BASE_DIR / "research" / "automaton",
            home / "automaton_upstream",
            home / ".conway",
        ],
        "personaplex": [
            _path_or_none(personaplex_cfg.get("repo_path", "")),
            _path_or_none(configured.get("personaplex_path", "")),
            BASE_DIR / "research" / "personaplex",
            home / "personaplex_upstream",
        ],
    }


def _first_repo_path(candidates: list[Path], markers: tuple[str, ...]) -> str:
    for candidate in candidates:
        try:
            if candidate is None or not candidate.exists():
                continue
            for marker in markers:
                if (candidate / marker).exists():
                    return str(candidate)
        except Exception:
            continue
    return ""


def collect_capabilities() -> dict:
    runtime = load_runtime_config()
    candidates = _integration_candidates()
    personaplex_cfg = runtime.get("personaplex", {})
    personaplex_url = str(personaplex_cfg.get("server_url", "") or "").strip()
    telegram_cfg = runtime.get("channels", {}).get("telegram", {})

    return {
        "voice_backend": runtime.get("voice_backend", "gemini_live"),
        "voice_name": runtime.get("voice_name", "Charon"),
        "live_model": runtime.get("live_model", ""),
        "gemini_api_configured": _api_key_configured(),
        "playwright_installed": _has_module("playwright"),
        "vision_installed": _has_module("cv2") and _has_module("mss"),
        "openrgb_installed": _has_module("openrgb"),
        "openrgb_sdk_reachable": _is_tcp_reachable("tcp://127.0.0.1:6742"),
        "mt5_installed": _has_module("MetaTrader5"),
        "ccxt_installed": _has_module("ccxt"),
        "mirofish_path": _first_repo_path(candidates["mirofish"], ("README.md", "README-EN.md", "backend")),
        "automaton_path": _first_repo_path(candidates["automaton"], ("ARCHITECTURE.md", "package.json", "src")),
        "personaplex_path": _first_repo_path(candidates["personaplex"], ("README.md", "moshi", "client")),
        "personaplex_enabled": bool(personaplex_cfg.get("enabled", False)),
        "personaplex_server_url": personaplex_url,
        "personaplex_server_reachable": bool(personaplex_url) and _is_tcp_reachable(personaplex_url),
        "telegram_bridge_enabled": bool(telegram_cfg.get("enabled", False)),
        "telegram_bot_configured": _telegram_token_configured(),
        "telegram_allowed_chat_count": len(telegram_cfg.get("allowed_chat_ids", []) or []),
    }


def format_capability_status() -> str:
    caps = collect_capabilities()
    lines = [
        f"Voice backend: {caps['voice_backend']}",
        f"Voice name: {caps['voice_name']}",
        f"Live model: {caps['live_model'] or 'unknown'}",
        f"Gemini API configured: {'yes' if caps['gemini_api_configured'] else 'no'}",
        f"Browser automation: {'ready' if caps['playwright_installed'] else 'missing playwright'}",
        f"Vision stack: {'ready' if caps['vision_installed'] else 'partial'}",
        (
            "RGB hardware control: ready"
            if caps["openrgb_installed"] and caps["openrgb_sdk_reachable"]
            else "RGB hardware control: package/sdk unavailable"
        ),
        f"MetaTrader5 bridge: {'ready' if caps['mt5_installed'] else 'not installed'}",
        f"CCXT bridge: {'ready' if caps['ccxt_installed'] else 'not installed'}",
        f"MiroFish repo: {caps['mirofish_path'] or 'not found'}",
        f"Automaton repo: {caps['automaton_path'] or 'not found'}",
        (
            f"PersonaPlex: configured at {caps['personaplex_server_url']}"
            if caps["personaplex_enabled"]
            else "PersonaPlex: disabled"
        ),
        (
            "Telegram bridge: ready"
            if caps["telegram_bridge_enabled"] and caps["telegram_bot_configured"]
            else "Telegram bridge: disabled or missing bot token"
        ),
    ]
    return "[CAPABILITY STATUS]\n" + "\n".join(f"- {line}" for line in lines)


def format_capability_report() -> str:
    caps = collect_capabilities()
    lines = [
        "AXIOM capability status",
        f"Voice backend: {caps['voice_backend']}",
        f"Voice name: {caps['voice_name']}",
        f"Live model: {caps['live_model'] or 'unknown'}",
        f"Gemini API: {'configured' if caps['gemini_api_configured'] else 'missing key'}",
        f"Playwright: {'installed' if caps['playwright_installed'] else 'missing'}",
        f"Vision stack: {'ready' if caps['vision_installed'] else 'partial'}",
        (
            "OpenRGB: installed and SDK reachable"
            if caps["openrgb_installed"] and caps["openrgb_sdk_reachable"]
            else "OpenRGB: not fully available"
        ),
        f"MetaTrader5: {'installed' if caps['mt5_installed'] else 'missing'}",
        f"CCXT: {'installed' if caps['ccxt_installed'] else 'missing'}",
        f"MiroFish path: {caps['mirofish_path'] or 'not found'}",
        f"Automaton path: {caps['automaton_path'] or 'not found'}",
        f"PersonaPlex path: {caps['personaplex_path'] or 'not found'}",
        (
            f"PersonaPlex server: reachable at {caps['personaplex_server_url']}"
            if caps["personaplex_server_reachable"]
            else f"PersonaPlex server: {'configured but offline' if caps['personaplex_enabled'] else 'disabled'}"
        ),
        (
            f"Telegram bridge: enabled ({caps['telegram_allowed_chat_count']} allowed chats)"
            if caps["telegram_bridge_enabled"]
            else "Telegram bridge: disabled"
        ),
        (
            "Telegram bot token: configured"
            if caps["telegram_bot_configured"]
            else "Telegram bot token: missing"
        ),
    ]
    return "\n".join(lines)
