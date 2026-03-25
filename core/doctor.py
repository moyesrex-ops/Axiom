import importlib.util
import sqlite3
from pathlib import Path

from core.agent_library import collect_agent_library_status
from core.autoresearch_bridge import collect_autoresearch_status
from core.automaton_bridge import collect_automaton_status
from core.dexter_bridge import collect_dexter_status
from core.lightpanda_bridge import collect_lightpanda_status
from core.mirofish_bridge import collect_mirofish_status
from core.pentagi_bridge import collect_pentagi_status
from core.runtime_config import load_runtime_config
from core.secret_config import get_secret
from core.skill_library import collect_skill_library_status
from memory import runtime_store


def _status_row(level: str, name: str, summary: str, detail: str = "") -> dict:
    return {
        "level": level,
        "name": name,
        "summary": summary,
        "detail": detail,
    }


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _memory_store_status() -> dict:
    try:
        runtime_store.init_runtime_store()
        db_path = runtime_store.DB_PATH
        with sqlite3.connect(db_path) as conn:
            conn.execute("SELECT COUNT(*) FROM sqlite_master")
        return {
            "ok": True,
            "db_path": str(db_path),
            "exists": db_path.exists(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "db_path": str(runtime_store.DB_PATH),
            "exists": Path(runtime_store.DB_PATH).exists(),
            "error": str(exc),
        }


def collect_doctor_report(limit: int = 6) -> dict:
    runtime = load_runtime_config()
    browser_cfg = runtime.get("browser", {}) or {}
    telegram_cfg = runtime.get("channels", {}).get("telegram", {}) or {}
    mirofish = collect_mirofish_status(limit=2)
    automaton = collect_automaton_status()
    lightpanda = collect_lightpanda_status()
    autoresearch = collect_autoresearch_status(limit=2)
    skills = collect_skill_library_status(limit=limit)
    agents = collect_agent_library_status(limit=limit)
    dexter = collect_dexter_status()
    pentagi = collect_pentagi_status()
    memory = _memory_store_status()

    checks = []
    api_ready = bool(get_secret("gemini_api_key", ["GEMINI_API_KEY"]))
    checks.append(
        _status_row(
            "pass" if api_ready else "fail",
            "Gemini API",
            "Configured" if api_ready else "Missing API key",
            "AXIOM cannot run live reasoning or delegated agents without it.",
        )
    )

    checks.append(
        _status_row(
            "pass" if memory["ok"] else "fail",
            "Memory Store",
            "SQLite runtime store reachable" if memory["ok"] else "Runtime store failed",
            memory.get("db_path", ""),
        )
    )

    playwright_ready = _has_module("playwright")
    backend = str(browser_cfg.get("backend", "playwright") or "playwright").strip().lower()
    if backend == "lightpanda":
        if lightpanda.get("reachable"):
            checks.append(_status_row("pass", "Browser Backend", "Lightpanda endpoint reachable", lightpanda.get("endpoint", "")))
        elif playwright_ready:
            checks.append(_status_row("warn", "Browser Backend", "Lightpanda selected but endpoint is down; Playwright fallback exists", lightpanda.get("endpoint", "")))
        else:
            checks.append(_status_row("fail", "Browser Backend", "Lightpanda selected but endpoint is down and Playwright is missing", lightpanda.get("endpoint", "")))
    else:
        checks.append(
            _status_row(
                "pass" if playwright_ready else "fail",
                "Browser Backend",
                "Playwright available" if playwright_ready else "Playwright missing",
                f"Configured backend: {backend}",
            )
        )

    telegram_enabled = bool(telegram_cfg.get("enabled", False))
    telegram_token = bool(
        get_secret("telegram_bot_token", ["AXIOM_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"])
    )
    if telegram_enabled and telegram_token:
        checks.append(
            _status_row(
                "pass",
                "Telegram",
                "Bridge enabled and token present",
                f"Allowed chats: {len(telegram_cfg.get('allowed_chat_ids', []) or [])}",
            )
        )
    elif telegram_enabled:
        checks.append(_status_row("fail", "Telegram", "Bridge enabled but bot token is missing"))
    else:
        checks.append(_status_row("info", "Telegram", "Bridge disabled"))

    if mirofish.get("repo_path"):
        checks.append(
            _status_row(
                "pass" if mirofish.get("backend_reachable") else "warn",
                "MiroFish",
                "Backend reachable" if mirofish.get("backend_reachable") else "Repo found but backend offline",
                mirofish.get("server_url", ""),
            )
        )
    else:
        checks.append(_status_row("info", "MiroFish", "Repo not detected"))

    if automaton.get("repo_path"):
        checks.append(
            _status_row(
                "pass" if automaton.get("built_entry") else "warn",
                "Automaton",
                "Built runtime detected" if automaton.get("built_entry") else "Repo found but build/runtime state is incomplete",
                automaton.get("repo_path", ""),
            )
        )
    else:
        checks.append(_status_row("info", "Automaton", "Repo not detected"))

    if lightpanda.get("repo_path"):
        checks.append(
            _status_row(
                "pass" if lightpanda.get("reachable") else "warn",
                "Lightpanda",
                "Endpoint reachable" if lightpanda.get("reachable") else "Repo found but endpoint offline",
                lightpanda.get("endpoint", ""),
            )
        )
    else:
        checks.append(_status_row("info", "Lightpanda", "Repo not detected"))

    if autoresearch.get("repo_path"):
        prepared = bool(autoresearch.get("uv_available")) and bool(autoresearch.get("tokenizer_ready")) and int(
            autoresearch.get("data_shards", 0) or 0
        ) > 0
        checks.append(
            _status_row(
                "pass" if prepared else "warn",
                "Autoresearch",
                "Prepared for experiments" if prepared else "Repo found but prep/training prerequisites are incomplete",
                autoresearch.get("repo_path", ""),
            )
        )
    else:
        checks.append(_status_row("info", "Autoresearch", "Repo not detected"))

    if skills.get("enabled"):
        checks.append(
            _status_row(
                "pass" if skills.get("total_skills", 0) else "warn",
                "Skill Library",
                f"{skills.get('total_skills', 0)} indexed skills across {skills.get('sources_count', 0)} sources",
            )
        )
    else:
        checks.append(_status_row("info", "Skill Library", "Disabled"))

    if agents.get("enabled"):
        checks.append(
            _status_row(
                "pass" if agents.get("total_agents", 0) else "warn",
                "Agent Library",
                f"{agents.get('total_agents', 0)} indexed agents across {agents.get('sources_count', 0)} sources",
            )
        )
    else:
        checks.append(_status_row("info", "Agent Library", "Disabled"))

    if dexter.get("repo_path"):
        checks.append(
            _status_row(
                "pass" if dexter.get("bun_available") else "warn",
                "Dexter",
                "Repo detected and Bun available" if dexter.get("bun_available") else "Repo detected but Bun is missing",
                dexter.get("repo_path", ""),
            )
        )
    else:
        checks.append(_status_row("info", "Dexter", "Repo not detected"))

    if pentagi.get("repo_path"):
        checks.append(
            _status_row(
                "warn" if pentagi.get("audit_notice_present") and not pentagi.get("source_available") else "pass",
                "PentAGI",
                (
                    "Repo detected but upstream source is currently unavailable"
                    if pentagi.get("audit_notice_present") and not pentagi.get("source_available")
                    else "Repo detected"
                ),
                pentagi.get("repo_path", ""),
            )
        )
    else:
        checks.append(_status_row("info", "PentAGI", "Repo not detected"))

    counts = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for row in checks:
        counts[row["level"]] = counts.get(row["level"], 0) + 1

    return {
        "checks": checks,
        "counts": counts,
    }


def format_doctor_report(limit: int = 6) -> str:
    report = collect_doctor_report(limit=limit)
    lines = [
        "AXIOM boot doctor",
        (
            f"Summary: pass={report['counts']['pass']} warn={report['counts']['warn']} "
            f"fail={report['counts']['fail']} info={report['counts']['info']}"
        ),
    ]
    for row in report["checks"]:
        label = row["level"].upper().ljust(4)
        detail = f" | {row['detail']}" if row.get("detail") else ""
        lines.append(f"- {label} | {row['name']}: {row['summary']}{detail}")
    return "\n".join(lines)


def boot_doctor_lines(limit: int = 6) -> list[str]:
    report = collect_doctor_report(limit=limit)
    lines = [
        (
            f"[DOCTOR] pass={report['counts']['pass']} warn={report['counts']['warn']} "
            f"fail={report['counts']['fail']} info={report['counts']['info']}"
        )
    ]
    for row in report["checks"]:
        lines.append(f"[DOCTOR] {row['level'].upper()} {row['name']}: {row['summary']}")
    return lines
