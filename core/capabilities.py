import importlib.util
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from core.automaton_bridge import collect_automaton_status
from core.mirofish_bridge import collect_mirofish_status
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
    mirofish = collect_mirofish_status(limit=3)
    automaton = collect_automaton_status()
    personaplex_cfg = runtime.get("personaplex", {})
    personaplex_url = str(personaplex_cfg.get("server_url", "") or "").strip()
    telegram_cfg = runtime.get("channels", {}).get("telegram", {})
    research_cfg = runtime.get("research", {}) or {}
    vane_url = str(research_cfg.get("vane_url", "") or "").strip()

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
        "mirofish_path": str(mirofish.get("repo_path", "") or ""),
        "mirofish_server_url": str(mirofish.get("server_url", "") or ""),
        "mirofish_backend_reachable": bool(mirofish.get("backend_reachable", False)),
        "mirofish_project_count": int(mirofish.get("projects_count", 0) or 0),
        "mirofish_simulation_count": int(mirofish.get("simulations_count", 0) or 0),
        "mirofish_report_count": int(mirofish.get("reports_count", 0) or 0),
        "mirofish_auto_start": bool(runtime.get("integrations", {}).get("mirofish_auto_start", False)),
        "automaton_path": str(automaton.get("repo_path", "") or ""),
        "automaton_state_dir": str(automaton.get("state_dir", "") or ""),
        "automaton_state_present": bool(automaton.get("state_exists", False)),
        "automaton_built": bool(automaton.get("built_entry")),
        "automaton_turn_count": int((automaton.get("db_snapshot", {}) or {}).get("turn_count", 0) or 0),
        "automaton_memory_ready": bool(
            automaton.get("db_path") or automaton.get("soul_path")
        ),
        "automaton_auto_start": bool(runtime.get("integrations", {}).get("automaton_auto_start", False)),
        "personaplex_path": _first_repo_path(candidates["personaplex"], ("README.md", "moshi", "client")),
        "personaplex_enabled": bool(personaplex_cfg.get("enabled", False)),
        "personaplex_server_url": personaplex_url,
        "personaplex_server_reachable": bool(personaplex_url) and _is_tcp_reachable(personaplex_url),
        "telegram_bridge_enabled": bool(telegram_cfg.get("enabled", False)),
        "telegram_bot_configured": _telegram_token_configured(),
        "telegram_allowed_chat_count": len(telegram_cfg.get("allowed_chat_ids", []) or []),
        "research_backend": str(research_cfg.get("backend", "axiom") or "axiom"),
        "vane_url": vane_url,
        "vane_reachable": bool(vane_url) and _is_tcp_reachable(vane_url),
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
        "System context inference: ready",
        f"MetaTrader5 bridge: {'ready' if caps['mt5_installed'] else 'not installed'}",
        f"CCXT bridge: {'ready' if caps['ccxt_installed'] else 'not installed'}",
        (
            f"MiroFish: repo at {caps['mirofish_path']} | backend {'up' if caps['mirofish_backend_reachable'] else 'down'} | "
            f"auto_start={'yes' if caps['mirofish_auto_start'] else 'no'} | "
            f"projects={caps['mirofish_project_count']} sims={caps['mirofish_simulation_count']} reports={caps['mirofish_report_count']}"
            if caps["mirofish_path"]
            else "MiroFish: repo not found"
        ),
        (
            f"Automaton: repo at {caps['automaton_path']} | state {'present' if caps['automaton_state_present'] else 'missing'} | "
            f"built={'yes' if caps['automaton_built'] else 'no'} | auto_start={'yes' if caps['automaton_auto_start'] else 'no'} | turns={caps['automaton_turn_count']}"
            if caps["automaton_path"]
            else "Automaton: repo not found"
        ),
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
        (
            f"Deep research backend: Vane at {caps['vane_url']}"
            if caps["vane_reachable"]
            else f"Deep research backend: {caps['research_backend']}"
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
        "System context inference: ready",
        f"MetaTrader5: {'installed' if caps['mt5_installed'] else 'missing'}",
        f"CCXT: {'installed' if caps['ccxt_installed'] else 'missing'}",
        f"MiroFish path: {caps['mirofish_path'] or 'not found'}",
        f"MiroFish server URL: {caps['mirofish_server_url'] or 'not configured'}",
        f"MiroFish backend: {'reachable' if caps['mirofish_backend_reachable'] else 'offline'}",
        f"MiroFish auto-start: {'enabled' if caps['mirofish_auto_start'] else 'disabled'}",
        f"MiroFish local state: projects={caps['mirofish_project_count']} simulations={caps['mirofish_simulation_count']} reports={caps['mirofish_report_count']}",
        f"Automaton path: {caps['automaton_path'] or 'not found'}",
        f"Automaton state dir: {caps['automaton_state_dir'] or 'not configured'}",
        f"Automaton state present: {'yes' if caps['automaton_state_present'] else 'no'}",
        f"Automaton built: {'yes' if caps['automaton_built'] else 'no'}",
        f"Automaton auto-start: {'enabled' if caps['automaton_auto_start'] else 'disabled'}",
        f"Automaton turns: {caps['automaton_turn_count']}",
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
        f"Research backend: {caps['research_backend']}",
        (
            f"Vane endpoint: reachable at {caps['vane_url']}"
            if caps["vane_reachable"]
            else f"Vane endpoint: {caps['vane_url'] or 'not configured'}"
        ),
    ]
    return "\n".join(lines)
