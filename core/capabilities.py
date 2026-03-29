import importlib.util
import json
import os
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from core.agent_library import collect_agent_library_status
from core.autoresearch_bridge import collect_autoresearch_status
from core.automaton_bridge import collect_automaton_status
from core.crucix_bridge import collect_crucix_status
from core.deerflow_bridge import collect_deerflow_status
from core.dexter_bridge import collect_dexter_status
from core.lightpanda_bridge import collect_lightpanda_status
from core.lossless_claw_bridge import collect_lossless_claw_status
from core.mirofish_bridge import collect_mirofish_status
from core.openfang_bridge import collect_openfang_status
from core.pentagi_bridge import collect_pentagi_status
from core.paperclip_bridge import collect_paperclip_status
from core.runtime_config import load_runtime_config
from core.secret_config import get_gemini_api_key, get_secret
from core.skill_library import collect_skill_library_status
from core.symphony_bridge import collect_symphony_status
from core.tradingagents_bridge import collect_tradingagents_status


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
    return bool(get_gemini_api_key())


def _telegram_token_configured() -> bool:
    return bool(
        get_secret(
            "telegram_bot_token",
            ["AXIOM_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"],
        )
    )


def _command_available(command: str) -> str:
    return shutil.which(command) or ""


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
    lightpanda = collect_lightpanda_status()
    skill_library = collect_skill_library_status(limit=4)
    agent_library = collect_agent_library_status(limit=4)
    autoresearch = collect_autoresearch_status(limit=3)
    dexter = collect_dexter_status()
    pentagi = collect_pentagi_status()
    tradingagents = collect_tradingagents_status(limit=3)
    deerflow = collect_deerflow_status(limit=3)
    paperclip = collect_paperclip_status()
    openfang = collect_openfang_status()
    symphony = collect_symphony_status()
    lossless_claw = collect_lossless_claw_status()
    personaplex_cfg = runtime.get("personaplex", {})
    personaplex_url = str(personaplex_cfg.get("server_url", "") or "").strip()
    telegram_cfg = runtime.get("channels", {}).get("telegram", {})
    research_cfg = runtime.get("research", {}) or {}
    routing_cfg = runtime.get("routing", {}) or {}
    learning_cfg = runtime.get("learning", {}) or {}
    vane_url = str(research_cfg.get("vane_url", "") or "").strip()
    autonomy_cfg = runtime.get("autonomy", {}) or {}
    crucix = collect_crucix_status()

    return {
        "startup_mode": "gemini_first",
        "startup_required_secret": "gemini_api_key",
        "startup_ready": _api_key_configured(),
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
        "automaton_configured": bool(automaton.get("config_path")),
        "automaton_db_present": bool(automaton.get("db_path")),
        "automaton_soul_present": bool(automaton.get("soul_path")),
        "automaton_api_key_present": bool(automaton.get("api_key_present", False)),
        "automaton_turn_count": int((automaton.get("db_snapshot", {}) or {}).get("turn_count", 0) or 0),
        "automaton_memory_ready": bool(
            automaton.get("db_path") or automaton.get("soul_path")
        ),
        "automaton_runtime_ready": bool(
            automaton.get("built_entry")
            and automaton.get("config_path")
            and automaton.get("api_key_present", False)
        ),
        "automaton_auto_start": bool(runtime.get("integrations", {}).get("automaton_auto_start", False)),
        "personaplex_path": _first_repo_path(candidates["personaplex"], ("README.md", "moshi", "client")),
        "personaplex_enabled": bool(personaplex_cfg.get("enabled", False)),
        "personaplex_server_url": personaplex_url,
        "personaplex_server_reachable": bool(personaplex_url) and _is_tcp_reachable(personaplex_url),
        "telegram_bridge_enabled": bool(telegram_cfg.get("enabled", False)),
        "telegram_bot_configured": _telegram_token_configured(),
        "telegram_allowed_chat_count": len(telegram_cfg.get("allowed_chat_ids", []) or []),
        "skill_library_enabled": bool(skill_library.get("enabled", False)),
        "skill_library_sources_count": int(skill_library.get("sources_count", 0) or 0),
        "skill_library_total_skills": int(skill_library.get("total_skills", 0) or 0),
        "agent_library_enabled": bool(agent_library.get("enabled", False)),
        "agent_library_sources_count": int(agent_library.get("sources_count", 0) or 0),
        "agent_library_total_agents": int(agent_library.get("total_agents", 0) or 0),
        "auto_specialists_enabled": bool(autonomy_cfg.get("auto_specialists", True)),
        "delegate_specialists_enabled": bool(autonomy_cfg.get("delegate_specialists", True)),
        "codex_cli_path": _command_available("codex"),
        "codex_cli_available": bool(_command_available("codex")),
        "dexter_repo_path": str(dexter.get("repo_path", "") or ""),
        "dexter_bun_available": bool(dexter.get("bun_available", False)),
        "dexter_tool_count": int(dexter.get("tool_count", 0) or 0),
        "pentagi_repo_path": str(pentagi.get("repo_path", "") or ""),
        "pentagi_source_available": bool(pentagi.get("source_available", False)),
        "pentagi_audit_notice": bool(pentagi.get("audit_notice_present", False)),
        "tradingagents_repo_path": str(tradingagents.get("repo_path", "") or ""),
        "tradingagents_venv_ready": bool(tradingagents.get("venv_ready", False)),
        "tradingagents_import_ready": bool(tradingagents.get("import_ready", False)),
        "tradingagents_role_count": int(tradingagents.get("role_count", 0) or 0),
        "tradingagents_runs_count": int(tradingagents.get("runs_count", 0) or 0),
        "tradingagents_provider": str(tradingagents.get("provider", "") or ""),
        "lightpanda_repo_path": str(lightpanda.get("repo_path", "") or ""),
        "lightpanda_endpoint": str(lightpanda.get("endpoint", "") or ""),
        "lightpanda_reachable": bool(lightpanda.get("reachable", False)),
        "lightpanda_backend": str(lightpanda.get("backend", "playwright") or "playwright"),
        "lightpanda_auto_start": bool(lightpanda.get("auto_start", False)),
        "autoresearch_repo_path": str(autoresearch.get("repo_path", "") or ""),
        "autoresearch_uv_ready": bool(autoresearch.get("uv_available", False)),
        "autoresearch_gpu_ready": bool(autoresearch.get("gpu_available", False)),
        "autoresearch_data_shards": int(autoresearch.get("data_shards", 0) or 0),
        "autoresearch_tokenizer_ready": bool(autoresearch.get("tokenizer_ready", False)),
        "autoresearch_results_count": int(autoresearch.get("results_count", 0) or 0),
        "deerflow_repo_path": str(deerflow.get("repo_path", "") or ""),
        "deerflow_gateway_url": str(deerflow.get("gateway_url", "") or ""),
        "deerflow_langgraph_url": str(deerflow.get("langgraph_url", "") or ""),
        "deerflow_proxy_reachable": bool(deerflow.get("proxy_reachable", False)),
        "deerflow_auto_start": bool(deerflow.get("auto_start", False)),
        "deerflow_managed_config": bool(deerflow.get("managed_config", False)),
        "deerflow_backend_venv_ready": bool(deerflow.get("backend_venv_ready", False)),
        "deerflow_gemini_api_key_present": bool(deerflow.get("gemini_api_key_present", False)),
        "deerflow_local_skill_count": int(deerflow.get("local_skill_count", 0) or 0),
        "deerflow_models_count": int(deerflow.get("models_count", 0) or 0),
        "deerflow_agents_count": int(deerflow.get("agents_count", 0) or 0),
        "paperclip_repo_path": str(paperclip.get("repo_path", "") or ""),
        "paperclip_api_url": str(paperclip.get("api_url", "") or ""),
        "paperclip_api_reachable": bool(paperclip.get("api_reachable", False)),
        "paperclip_auto_start": bool(paperclip.get("auto_start", False)),
        "paperclip_skills_count": int(paperclip.get("skills_count", 0) or 0),
        "openfang_repo_path": str(openfang.get("repo_path", "") or ""),
        "openfang_dashboard_url": str(openfang.get("dashboard_url", "") or ""),
        "openfang_dashboard_reachable": bool(openfang.get("dashboard_reachable", False)),
        "openfang_auto_start": bool(openfang.get("auto_start", False)),
        "openfang_hands_count": int(openfang.get("bundled_hands", 0) or 0),
        "openfang_skills_count": int(openfang.get("bundled_skills", 0) or 0),
        "symphony_repo_path": str(symphony.get("repo_path", "") or ""),
        "symphony_spec_present": bool(symphony.get("spec_present", False)),
        "symphony_elixir_reference_present": bool(symphony.get("elixir_reference_present", False)),
        "symphony_workflow_path": str(symphony.get("workflow_path", "") or ""),
        "lossless_claw_repo_path": str(lossless_claw.get("repo_path", "") or ""),
        "lossless_claw_openclaw_available": bool(lossless_claw.get("openclaw_available", False)),
        "lossless_claw_plugin_manifest_present": bool(lossless_claw.get("plugin_manifest_present", False)),
        "lossless_claw_database_path": str(lossless_claw.get("database_path", "") or ""),
        "research_backend": str(research_cfg.get("backend", "axiom") or "axiom"),
        "vane_url": vane_url,
        "vane_reachable": bool(vane_url) and _is_tcp_reachable(vane_url),
        "routing_local_provider": str(routing_cfg.get("local_provider", "ollama") or "ollama"),
        "routing_local_endpoint": str(routing_cfg.get("local_endpoint", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"),
        "routing_local_model": str(routing_cfg.get("local_model", "qwen2.5:7b-instruct") or "qwen2.5:7b-instruct"),
        "routing_local_enabled": bool(routing_cfg.get("prefer_local_classifier", True)),
        "learning_enabled": bool(learning_cfg.get("enabled", True)),
        "learning_auto_run": bool(learning_cfg.get("auto_run", True)),
        "learning_interval_seconds": int(learning_cfg.get("interval_seconds", 1800) or 1800),
        "crucix_repo_path": str(crucix.get("repo_path", "") or ""),
        "crucix_api_url": str(crucix.get("server_url", "") or ""),
        "crucix_reachable": bool(crucix.get("reachable", False)),
        "crucix_idea_count": int(crucix.get("idea_count", 0) or 0),
    }


def format_operator_surface(limit: int = 4) -> str:
    caps = collect_capabilities()
    skill_status = collect_skill_library_status(limit=max(int(limit), 1))
    agent_status = collect_agent_library_status(limit=max(int(limit), 1))

    lines = [
        "[OPERATOR SURFACE]",
        "AXIOM runs one shared execution spine across local voice and Telegram.",
        "Deferred work now runs through a shared mission journal with persisted phases, plan revisions, step checkpoints, and event history.",
        "Use cmd_control for real PowerShell, CMD, Bash, or VS Code integrated-terminal work.",
        "Use system_capabilities as the source of truth when there is any doubt about live integrations.",
    ]

    if caps["telegram_bridge_enabled"] and caps["telegram_bot_configured"]:
        lines.append(
            f"Telegram is live with {caps['telegram_allowed_chat_count']} allowed chat(s) and shares task state with voice."
        )
    else:
        lines.append("Telegram is disabled or missing a bot token, so voice remains the primary live channel.")

    if skill_status["enabled"] and skill_status["sources_count"]:
        source_names = ", ".join(source["name"] for source in skill_status["sources"][: max(int(limit), 1)])
        lines.append(
            f"Skills indexed: {skill_status['total_skills']} across {skill_status['sources_count']} sources. "
            f"Strong sources currently detected: {source_names}."
        )
        lines.append(
            "For complex builds, reviews, debugging, planning, or recent-trend research, pull skill_library recommend/read before executing."
        )
    else:
        lines.append("No external skill libraries are currently indexed.")

    if agent_status["enabled"] and agent_status["sources_count"]:
        source_names = ", ".join(source["name"] for source in agent_status["sources"][: max(int(limit), 1)])
        lines.append(
            f"Agent catalogs indexed: {agent_status['total_agents']} across {agent_status['sources_count']} sources. "
            f"Notable sources: {source_names}."
        )
        lines.append(
            "For complex coding, research, security, or orchestration tasks, use agent_library recommend/read and delegate when supervised specialist input will materially help."
        )
    else:
        lines.append("No external agent catalogs are currently indexed.")

    if caps.get("deerflow_repo_path"):
        lines.append(
            f"DeerFlow sidecar is detected and its gateway is {'reachable' if caps.get('deerflow_proxy_reachable') else 'offline'}."
        )
    if caps.get("lightpanda_repo_path"):
        lines.append(
            f"Lightpanda backend is configured for browser acceleration and is {'reachable' if caps.get('lightpanda_reachable') else 'not yet live'}."
        )
    if caps.get("crucix_repo_path"):
        lines.append(
            f"Crucix intelligence engine is {'reachable' if caps.get('crucix_reachable') else 'configured but offline'} at {caps.get('crucix_api_url', 'unknown')}."
        )

    lines.append(
        f"Learning daemon is {'enabled' if caps.get('learning_enabled') and caps.get('learning_auto_run') else 'available but not auto-running'}."
    )

    lines.append("Never simulate status, artifacts, or execution. Name the exact path, URL, task id, or failure.")
    return "\n".join(f"- {line}" if index else line for index, line in enumerate(lines))


def format_capability_status() -> str:
    caps = collect_capabilities()
    lines = [
        "Startup mode: Gemini-first",
        f"Base startup ready: {'yes' if caps['startup_ready'] else 'no'}",
        f"Required secret: {caps['startup_required_secret']}",
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
            f"Automaton: repo at {caps['automaton_path']} | configured={'yes' if caps['automaton_configured'] else 'no'} | "
            f"memory={'yes' if caps['automaton_memory_ready'] else 'no'} | api_key={'yes' if caps['automaton_api_key_present'] else 'no'} | "
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
            f"Skill library: {caps['skill_library_total_skills']} indexed skills across {caps['skill_library_sources_count']} sources"
            if caps["skill_library_enabled"] and caps["skill_library_sources_count"]
            else "Skill library: no external skill sources detected"
        ),
        (
            f"Agent library: {caps['agent_library_total_agents']} indexed agents across {caps['agent_library_sources_count']} sources"
            if caps["agent_library_enabled"] and caps["agent_library_sources_count"]
            else "Agent library: no external agent sources detected"
        ),
        (
            f"Autonomous specialists: enabled | preflight={'yes' if caps['delegate_specialists_enabled'] else 'no'}"
            if caps["auto_specialists_enabled"]
            else "Autonomous specialists: disabled"
        ),
        (
            f"Codex CLI builder: ready at {caps['codex_cli_path']}"
            if caps["codex_cli_available"]
            else "Codex CLI builder: not installed"
        ),
        (
            f"Dexter: repo at {caps['dexter_repo_path']} | bun={'yes' if caps['dexter_bun_available'] else 'no'} | tools={caps['dexter_tool_count']}"
            if caps["dexter_repo_path"]
            else "Dexter: repo not found"
        ),
        (
            "PentAGI: repo detected but upstream source is unavailable during a license audit"
            if caps["pentagi_repo_path"] and caps["pentagi_audit_notice"] and not caps["pentagi_source_available"]
            else f"PentAGI: repo at {caps['pentagi_repo_path']}"
            if caps["pentagi_repo_path"]
            else "PentAGI: repo not found"
        ),
        (
            f"TradingAgents: repo at {caps['tradingagents_repo_path']} | "
            f"venv={'yes' if caps['tradingagents_venv_ready'] else 'no'} | "
            f"import={'yes' if caps['tradingagents_import_ready'] else 'no'} | "
            f"roles={caps['tradingagents_role_count']} runs={caps['tradingagents_runs_count']}"
            if caps["tradingagents_repo_path"]
            else "TradingAgents: repo not found"
        ),
        (
            f"Lightpanda: endpoint {'up' if caps['lightpanda_reachable'] else 'down'} at {caps['lightpanda_endpoint']} | "
            f"backend={caps['lightpanda_backend']} | auto_start={'yes' if caps['lightpanda_auto_start'] else 'no'}"
            if caps["lightpanda_repo_path"]
            else "Lightpanda: repo not found"
        ),
        (
            f"Autoresearch: repo at {caps['autoresearch_repo_path']} | shards={caps['autoresearch_data_shards']} | "
            f"tokenizer={'ready' if caps['autoresearch_tokenizer_ready'] else 'missing'} | results={caps['autoresearch_results_count']}"
            if caps["autoresearch_repo_path"]
            else "Autoresearch: repo not found"
        ),
        (
            f"DeerFlow: gateway {'up' if caps['deerflow_proxy_reachable'] else 'down'} at {caps['deerflow_gateway_url']} | "
            f"auto_start={'yes' if caps['deerflow_auto_start'] else 'no'} | "
            f"local_skills={caps['deerflow_local_skill_count']} remote_models={caps['deerflow_models_count']} remote_agents={caps['deerflow_agents_count']}"
            if caps["deerflow_repo_path"]
            else "DeerFlow: repo not found"
        ),
        (
            f"Paperclip: API {'up' if caps['paperclip_api_reachable'] else 'down'} at {caps['paperclip_api_url']} | "
            f"auto_start={'yes' if caps['paperclip_auto_start'] else 'no'} | skills={caps['paperclip_skills_count']}"
            if caps["paperclip_repo_path"]
            else "Paperclip: repo not found"
        ),
        (
            f"OpenFang: dashboard {'up' if caps['openfang_dashboard_reachable'] else 'down'} at {caps['openfang_dashboard_url']} | "
            f"auto_start={'yes' if caps['openfang_auto_start'] else 'no'} | hands={caps['openfang_hands_count']} skills={caps['openfang_skills_count']}"
            if caps["openfang_repo_path"]
            else "OpenFang: repo not found"
        ),
        (
            f"Symphony: repo at {caps['symphony_repo_path']} | spec={'yes' if caps['symphony_spec_present'] else 'no'} | "
            f"workflow={caps['symphony_workflow_path'] or 'WORKFLOW.md'}"
            if caps["symphony_repo_path"]
            else "Symphony: repo not found"
        ),
        (
            f"lossless-claw: repo at {caps['lossless_claw_repo_path']} | plugin_manifest={'yes' if caps['lossless_claw_plugin_manifest_present'] else 'no'} | "
            f"openclaw={'yes' if caps['lossless_claw_openclaw_available'] else 'no'}"
            if caps["lossless_claw_repo_path"]
            else "lossless-claw: repo not found"
        ),
        (
            f"Deep research backend: Vane at {caps['vane_url']}"
            if caps["vane_reachable"]
            else f"Deep research backend: {caps['research_backend']}"
        ),
        (
            f"Crucix: API {'up' if caps['crucix_reachable'] else 'down'} at {caps['crucix_api_url']} | ideas={caps['crucix_idea_count']}"
            if caps["crucix_repo_path"]
            else "Crucix: repo not found"
        ),
        (
            f"Local routing: {caps['routing_local_provider']} {caps['routing_local_model']} at {caps['routing_local_endpoint']}"
            if caps["routing_local_enabled"]
            else "Local routing: disabled"
        ),
        (
            f"Learning daemon: auto-run every {caps['learning_interval_seconds']}s"
            if caps["learning_enabled"] and caps["learning_auto_run"]
            else "Learning daemon: disabled or manual"
        ),
    ]
    return "[CAPABILITY STATUS]\n" + "\n".join(f"- {line}" for line in lines)


def format_capability_report() -> str:
    caps = collect_capabilities()
    lines = [
        "AXIOM capability status",
        f"Startup mode: Gemini-first",
        f"Base startup ready: {'yes' if caps['startup_ready'] else 'no'}",
        f"Required startup secret: {caps['startup_required_secret']}",
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
        f"Automaton state dir exists: {'yes' if caps['automaton_state_present'] else 'no'}",
        f"Automaton built: {'yes' if caps['automaton_built'] else 'no'}",
        f"Automaton config present: {'yes' if caps['automaton_configured'] else 'no'}",
        f"Automaton API key present: {'yes' if caps['automaton_api_key_present'] else 'no'}",
        f"Automaton DB present: {'yes' if caps['automaton_db_present'] else 'no'}",
        f"Automaton SOUL present: {'yes' if caps['automaton_soul_present'] else 'no'}",
        f"Automaton runtime ready: {'yes' if caps['automaton_runtime_ready'] else 'no'}",
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
        (
            f"Skill library: {caps['skill_library_total_skills']} indexed skills across {caps['skill_library_sources_count']} sources"
            if caps["skill_library_enabled"] and caps["skill_library_sources_count"]
            else "Skill library: disabled or no sources detected"
        ),
        (
            f"Agent library: {caps['agent_library_total_agents']} indexed agents across {caps['agent_library_sources_count']} sources"
            if caps["agent_library_enabled"] and caps["agent_library_sources_count"]
            else "Agent library: disabled or no sources detected"
        ),
        (
            f"Autonomous specialists: enabled | specialist preflight={'yes' if caps['delegate_specialists_enabled'] else 'no'}"
            if caps["auto_specialists_enabled"]
            else "Autonomous specialists: disabled"
        ),
        f"Codex CLI: {caps['codex_cli_path'] or 'not installed'}",
        f"Dexter repo path: {caps['dexter_repo_path'] or 'not found'}",
        f"Dexter Bun ready: {'yes' if caps['dexter_bun_available'] else 'no'}",
        f"Dexter tool modules: {caps['dexter_tool_count']}",
        f"PentAGI repo path: {caps['pentagi_repo_path'] or 'not found'}",
        f"PentAGI source available: {'yes' if caps['pentagi_source_available'] else 'no'}",
        f"PentAGI license audit notice: {'yes' if caps['pentagi_audit_notice'] else 'no'}",
        f"TradingAgents repo path: {caps['tradingagents_repo_path'] or 'not found'}",
        f"TradingAgents sidecar venv: {'ready' if caps['tradingagents_venv_ready'] else 'missing'}",
        f"TradingAgents import check: {'ready' if caps['tradingagents_import_ready'] else 'not ready'}",
        f"TradingAgents role modules: {caps['tradingagents_role_count']}",
        f"TradingAgents logged runs: {caps['tradingagents_runs_count']}",
        f"TradingAgents provider: {caps['tradingagents_provider'] or 'unknown'}",
        f"Lightpanda repo path: {caps['lightpanda_repo_path'] or 'not found'}",
        f"Lightpanda endpoint: {caps['lightpanda_endpoint'] or 'not configured'}",
        f"Lightpanda endpoint reachable: {'yes' if caps['lightpanda_reachable'] else 'no'}",
        f"Lightpanda backend setting: {caps['lightpanda_backend']}",
        f"Lightpanda auto-start: {'enabled' if caps['lightpanda_auto_start'] else 'disabled'}",
        f"Autoresearch repo path: {caps['autoresearch_repo_path'] or 'not found'}",
        f"Autoresearch uv ready: {'yes' if caps['autoresearch_uv_ready'] else 'no'}",
        f"Autoresearch GPU ready: {'yes' if caps['autoresearch_gpu_ready'] else 'no'}",
        f"Autoresearch data shards: {caps['autoresearch_data_shards']}",
        f"Autoresearch tokenizer ready: {'yes' if caps['autoresearch_tokenizer_ready'] else 'no'}",
        f"Autoresearch logged results: {caps['autoresearch_results_count']}",
        f"DeerFlow repo path: {caps['deerflow_repo_path'] or 'not found'}",
        f"DeerFlow gateway URL: {caps['deerflow_gateway_url'] or 'not configured'}",
        f"DeerFlow proxy reachable: {'yes' if caps['deerflow_proxy_reachable'] else 'no'}",
        f"DeerFlow auto-start: {'enabled' if caps['deerflow_auto_start'] else 'disabled'}",
        f"DeerFlow managed config: {'yes' if caps['deerflow_managed_config'] else 'no'}",
        f"DeerFlow backend venv ready: {'yes' if caps['deerflow_backend_venv_ready'] else 'no'}",
        f"DeerFlow Gemini key available: {'yes' if caps['deerflow_gemini_api_key_present'] else 'no'}",
        f"DeerFlow local skills: {caps['deerflow_local_skill_count']}",
        f"DeerFlow remote models: {caps['deerflow_models_count']}",
        f"DeerFlow remote agents: {caps['deerflow_agents_count']}",
        f"Paperclip repo path: {caps['paperclip_repo_path'] or 'not found'}",
        f"Paperclip API URL: {caps['paperclip_api_url'] or 'not configured'}",
        f"Paperclip API reachable: {'yes' if caps['paperclip_api_reachable'] else 'no'}",
        f"Paperclip auto-start: {'enabled' if caps['paperclip_auto_start'] else 'disabled'}",
        f"Paperclip skills: {caps['paperclip_skills_count']}",
        f"OpenFang repo path: {caps['openfang_repo_path'] or 'not found'}",
        f"OpenFang dashboard URL: {caps['openfang_dashboard_url'] or 'not configured'}",
        f"OpenFang dashboard reachable: {'yes' if caps['openfang_dashboard_reachable'] else 'no'}",
        f"OpenFang auto-start: {'enabled' if caps['openfang_auto_start'] else 'disabled'}",
        f"OpenFang bundled hands: {caps['openfang_hands_count']}",
        f"OpenFang bundled skills: {caps['openfang_skills_count']}",
        f"Symphony repo path: {caps['symphony_repo_path'] or 'not found'}",
        f"Symphony spec present: {'yes' if caps['symphony_spec_present'] else 'no'}",
        f"Symphony Elixir reference present: {'yes' if caps['symphony_elixir_reference_present'] else 'no'}",
        f"Symphony workflow contract path: {caps['symphony_workflow_path'] or 'WORKFLOW.md'}",
        f"lossless-claw repo path: {caps['lossless_claw_repo_path'] or 'not found'}",
        f"lossless-claw database path: {caps['lossless_claw_database_path'] or 'default OpenClaw path'}",
        f"lossless-claw openclaw command: {'ready' if caps['lossless_claw_openclaw_available'] else 'missing'}",
        f"lossless-claw plugin manifest: {'yes' if caps['lossless_claw_plugin_manifest_present'] else 'no'}",
        f"Research backend: {caps['research_backend']}",
        (
            f"Vane endpoint: reachable at {caps['vane_url']}"
            if caps["vane_reachable"]
            else f"Vane endpoint: {caps['vane_url'] or 'not configured'}"
        ),
        f"Crucix repo path: {caps['crucix_repo_path'] or 'not found'}",
        f"Crucix API URL: {caps['crucix_api_url'] or 'not configured'}",
        f"Crucix API reachable: {'yes' if caps['crucix_reachable'] else 'no'}",
        f"Crucix surfaced ideas: {caps['crucix_idea_count']}",
        f"Local routing enabled: {'yes' if caps['routing_local_enabled'] else 'no'}",
        f"Local routing provider: {caps['routing_local_provider']}",
        f"Local routing endpoint: {caps['routing_local_endpoint']}",
        f"Local routing model: {caps['routing_local_model']}",
        f"Learning enabled: {'yes' if caps['learning_enabled'] else 'no'}",
        f"Learning auto-run: {'yes' if caps['learning_auto_run'] else 'no'}",
        f"Learning interval seconds: {caps['learning_interval_seconds']}",
    ]
    return "\n".join(lines)
