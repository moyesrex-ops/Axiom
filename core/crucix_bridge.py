import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from core.runtime_config import load_runtime_config, update_runtime_config
from core.secret_config import get_gemini_api_key


DEFAULT_CRUCIX_URL = "http://127.0.0.1:3117"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _crucix_config() -> dict:
    return load_runtime_config().get("crucix", {}) or {}


def configure_crucix(updates: dict) -> dict:
    return update_runtime_config({"crucix": updates or {}})


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _bridge_logs_dir(name: str) -> Path:
    candidates = [
        BASE_DIR / ".axiom_logs" / "integrations" / name,
        Path.home() / ".axiom_logs" / "integrations" / name,
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    raise PermissionError("AXIOM could not create an integration log directory.")


def _windows_creationflags() -> list[int]:
    if os.name != "nt":
        return [0]
    create_new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    flags = [
        create_new_group | detached | no_window | breakaway,
        create_new_group | detached | no_window,
        create_new_group | no_window,
        0,
    ]
    return list(dict.fromkeys(flags))


def _candidate_repo_paths() -> list[Path]:
    home = Path.home()
    cfg = _crucix_config()
    return [
        path
        for path in [
            _path_or_none(cfg.get("repo_path", "")),
            BASE_DIR / "research" / "Crucix",
            home / "Crucix",
            home / "Axiom_research" / "external" / "Crucix",
        ]
        if path is not None
    ]


def resolve_crucix_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "server.mjs").exists() and (candidate / "package.json").exists():
                return candidate
        except Exception:
            continue
    return None


def crucix_server_url() -> str:
    cfg = _crucix_config()
    return str(cfg.get("api_url", "") or DEFAULT_CRUCIX_URL).strip() or DEFAULT_CRUCIX_URL


def _http_json(url: str, timeout: float = 2.5) -> tuple[dict | list | None, str]:
    try:
        req = urlrequest.Request(url, method="GET")
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}"), ""
    except urlerror.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except urlerror.URLError as exc:
        return None, str(exc.reason or exc)
    except Exception as exc:
        return None, str(exc)


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _truncate(text: str, limit: int = 240) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _market_keywords(asset: str) -> set[str]:
    value = str(asset or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", value))
    if "bitcoin" in value or "btc" in tokens or "btc" in value:
        tokens.update({"bitcoin", "btc", "crypto", "ethereum", "defi", "memecoins"})
    if "gold" in value or "xau" in tokens or "xau" in value:
        tokens.update({"gold", "inflation", "rates", "fed", "safe havens", "commodities"})
    if "eurusd" in value or ("eur" in tokens and "usd" in tokens):
        tokens.update({"forex", "eur", "usd", "currency", "central banks", "geopolitics"})
    if "usd" in tokens:
        tokens.update({"fed", "rates", "inflation"})
    if "spy" in tokens or "qqq" in tokens or "spy" in value or "qqq" in value or "stocks" in tokens or "equity" in tokens:
        tokens.update({"tech", "growth", "value", "earnings", "fed", "market"})
    return {token for token in tokens if token}


def _score_text(text: str, keywords: set[str]) -> int:
    haystack = str(text or "").lower()
    score = 0
    for keyword in keywords:
        if keyword and keyword in haystack:
            score += 1
    return score


def _latest_run_snapshot(repo_path: Path | None) -> dict:
    if repo_path is None:
        return {}
    runs_dir = repo_path / "runs"
    if not runs_dir.exists():
        return {}

    latest_json = None
    latest_mtime = 0.0
    for candidate in runs_dir.rglob("*.json"):
        try:
            mtime = candidate.stat().st_mtime
        except Exception:
            continue
        if mtime > latest_mtime:
            latest_json = candidate
            latest_mtime = mtime

    if latest_json is None:
        return {}

    payload = _read_json(latest_json)
    if not isinstance(payload, dict):
        return {"latest_file": str(latest_json)}
    return {
        "latest_file": str(latest_json),
        "latest_file_mtime": latest_mtime,
        "payload_preview": _truncate(json.dumps(payload, ensure_ascii=False), 400),
    }


def _crucix_runtime_env() -> dict:
    runtime = load_runtime_config()
    cfg = runtime.get("crucix", {}) or {}
    env = dict(os.environ)

    if not bool(cfg.get("inherit_axiom_gemini", True)):
        return env

    if env.get("LLM_PROVIDER") and env.get("LLM_API_KEY"):
        return env

    provider = str(cfg.get("llm_provider", "gemini") or "gemini").strip().lower()
    if provider != "gemini":
        return env

    api_key = get_gemini_api_key()
    if not api_key:
        return env

    text_models = runtime.get("text_models", {}) or {}
    model = (
        str(cfg.get("llm_model", "") or "").strip()
        or str(text_models.get("fast", "") or "").strip()
        or str(text_models.get("default", "") or "").strip()
        or "gemini-2.5-flash"
    )
    env.setdefault("LLM_PROVIDER", "gemini")
    env.setdefault("LLM_API_KEY", api_key)
    env.setdefault("LLM_MODEL", model)
    return env


def collect_crucix_status() -> dict:
    repo_path = resolve_crucix_repo_path()
    server_url = crucix_server_url().rstrip("/")
    health, health_error = _http_json(f"{server_url}/api/health")
    data, data_error = _http_json(f"{server_url}/api/data")
    latest_snapshot = _latest_run_snapshot(repo_path)

    health_dict = health if isinstance(health, dict) else {}
    data_dict = data if isinstance(data, dict) else {}

    meta = data_dict.get("meta", {}) if isinstance(data_dict.get("meta", {}), dict) else {}
    ideas = data_dict.get("ideas", []) if isinstance(data_dict.get("ideas", []), list) else []

    return {
        "repo_path": str(repo_path) if repo_path else "",
        "server_url": server_url,
        "reachable": bool(health_dict.get("status") == "ok"),
        "health_error": health_error,
        "data_error": data_error,
        "uptime_seconds": int(health_dict.get("uptime", 0) or 0),
        "last_sweep": str(health_dict.get("lastSweep", "") or ""),
        "next_sweep": str(health_dict.get("nextSweep", "") or ""),
        "sweep_in_progress": bool(health_dict.get("sweepInProgress", False)),
        "sources_ok": int(health_dict.get("sourcesOk", 0) or 0),
        "sources_failed": int(health_dict.get("sourcesFailed", 0) or 0),
        "llm_enabled": bool(health_dict.get("llmEnabled", False)),
        "llm_provider": str(health_dict.get("llmProvider", "") or "").strip(),
        "idea_count": len(ideas),
        "top_ideas": [str(item.get("title", "") or "").strip() for item in ideas[:3] if isinstance(item, dict)],
        "latest_run": latest_snapshot,
        "dashboard_data_preview": _truncate(json.dumps(data_dict, ensure_ascii=False), 500) if data_dict else "",
    }


def get_crucix_market_context(asset: str, limit: int = 6) -> dict:
    status = collect_crucix_status()
    server_url = str(status.get("server_url", "") or "").rstrip("/")
    payload, payload_error = _http_json(f"{server_url}/api/data") if server_url else (None, "server url missing")
    data = payload if isinstance(payload, dict) else {}
    keywords = _market_keywords(asset)

    market_snapshot = []
    markets = data.get("markets", {}) if isinstance(data.get("markets", {}), dict) else {}
    commodities = markets.get("commodities", []) if isinstance(markets.get("commodities", []), list) else []
    crypto = markets.get("crypto", []) if isinstance(markets.get("crypto", []), list) else []
    indexes = markets.get("indexes", []) if isinstance(markets.get("indexes", []), list) else []
    vix = markets.get("vix", {}) if isinstance(markets.get("vix", {}), dict) else {}
    treasury = data.get("treasury", {}) if isinstance(data.get("treasury", {}), dict) else {}
    gscpi = data.get("gscpi", {}) if isinstance(data.get("gscpi", {}), dict) else {}
    energy = data.get("energy", {}) if isinstance(data.get("energy", {}), dict) else {}

    if "gold" in keywords or "xau" in keywords:
        for row in commodities:
            if str(row.get("symbol", "")).upper() == "GC=F" or "gold" in str(row.get("name", "")).lower():
                market_snapshot.append(
                    f"Gold {row.get('price')} ({row.get('changePct')}%); WTI {energy.get('wti', 'n/a')}; Brent {energy.get('brent', 'n/a')}"
                )
                break
    if "bitcoin" in keywords or "btc" in keywords:
        for row in crypto:
            if str(row.get("symbol", "")).upper() == "BTC-USD" or "bitcoin" in str(row.get("name", "")).lower():
                market_snapshot.append(
                    f"Bitcoin {row.get('price')} ({row.get('changePct')}%); ETH snapshot available"
                )
                break
    if "eur" in keywords or "usd" in keywords or "forex" in keywords:
        if vix:
            market_snapshot.append(
                f"VIX {vix.get('value', 'n/a')} ({vix.get('changePct', 'n/a')}%); GSCPI {gscpi.get('value', 'n/a')} ({gscpi.get('interpretation', 'n/a')})"
            )
        if treasury.get("signals"):
            market_snapshot.extend(str(item).strip() for item in treasury.get("signals", [])[:2] if str(item).strip())
    if not market_snapshot:
        selected_indexes = []
        for symbol in ("SPY", "QQQ", "DIA", "IWM"):
            for row in indexes:
                if str(row.get("symbol", "")).upper() == symbol:
                    selected_indexes.append(f"{symbol} {row.get('price')} ({row.get('changePct')}%)")
                    break
        if selected_indexes:
            market_snapshot.append(" | ".join(selected_indexes[:3]))
        if vix:
            market_snapshot.append(f"VIX {vix.get('value', 'n/a')} ({vix.get('changePct', 'n/a')}%)")

    relevant_headlines = []
    for row in data.get("newsFeed", []) or []:
        if not isinstance(row, dict):
            continue
        combined = " ".join(
            [
                str(row.get("headline", "")),
                str(row.get("source", "")),
                str(row.get("region", "")),
            ]
        )
        score = _score_text(combined, keywords)
        if bool(row.get("urgent")):
            score += 1
        if score > 0:
            relevant_headlines.append((score, row))
    relevant_headlines.sort(key=lambda item: item[0], reverse=True)

    urgent_posts = []
    for row in ((data.get("tg", {}) or {}).get("urgent", []) or []):
        if not isinstance(row, dict):
            continue
        combined = " ".join([str(row.get("channel", "")), str(row.get("text", ""))])
        score = _score_text(combined, keywords)
        if score > 0:
            urgent_posts.append((score, row))
    urgent_posts.sort(key=lambda item: item[0], reverse=True)

    ideas = []
    for row in data.get("ideas", []) or []:
        if not isinstance(row, dict):
            continue
        combined = " ".join([str(row.get("title", "")), str(row.get("summary", ""))])
        score = _score_text(combined, keywords)
        if score > 0:
            ideas.append((score, row))
    ideas.sort(key=lambda item: item[0], reverse=True)

    return {
        "available": bool(server_url and (status.get("reachable") or data)),
        "reachable": bool(status.get("reachable")),
        "repo_path": str(status.get("repo_path", "") or ""),
        "server_url": server_url,
        "last_sweep": str(status.get("last_sweep", "") or ""),
        "llm_enabled": bool(status.get("llm_enabled", False)),
        "llm_provider": str(status.get("llm_provider", "") or ""),
        "market_snapshot": [str(item).strip() for item in market_snapshot if str(item).strip()],
        "relevant_headlines": [row for _, row in relevant_headlines[: max(int(limit), 1)]],
        "urgent_posts": [row for _, row in urgent_posts[:3]],
        "ideas": [row for _, row in ideas[:3]],
        "error": payload_error,
    }


def format_crucix_market_context(asset: str, limit: int = 6) -> str:
    context = get_crucix_market_context(asset, limit=limit)
    if not context.get("available"):
        return "Crucix market context is unavailable because the repo or API is not available."

    lines = [f"Crucix live market context for {asset}"]
    lines.append(f"API reachable: {'yes' if context.get('reachable') else 'no'}")
    if context.get("last_sweep"):
        lines.append(f"Last sweep: {context['last_sweep']}")
    if context.get("llm_provider"):
        lines.append(
            f"LLM layer: {'enabled' if context.get('llm_enabled') else 'disabled'} ({context['llm_provider']})"
        )
    elif context.get("llm_enabled"):
        lines.append("LLM layer: enabled")
    else:
        lines.append("LLM layer: disabled")
    if context.get("market_snapshot"):
        lines.append("Market snapshot:")
        for row in context["market_snapshot"][:4]:
            lines.append(f"- {_truncate(row, 180)}")
    if context.get("relevant_headlines"):
        lines.append("Relevant headlines:")
        for row in context["relevant_headlines"][: max(int(limit), 1)]:
            lines.append(
                f"- {_truncate(row.get('headline', ''), 180)}"
                + (f" | source={row.get('source', '')}" if row.get("source") else "")
            )
    if context.get("urgent_posts"):
        lines.append("Urgent OSINT posts:")
        for row in context["urgent_posts"][:3]:
            lines.append(f"- {_truncate(row.get('text', ''), 180)}")
    if context.get("ideas"):
        lines.append("Live ideas:")
        for row in context["ideas"][:3]:
            title = str(row.get("title", "") or row.get("summary", "")).strip()
            if title:
                lines.append(f"- {_truncate(title, 180)}")
    if not context.get("reachable") and context.get("error"):
        lines.append(f"API error: {context['error']}")
    return "\n".join(lines)


def format_crucix_status() -> str:
    status = collect_crucix_status()
    lines = ["[CRUCIX STATUS]"]
    if status["repo_path"]:
        lines.append(f"- Repo path: {status['repo_path']}")
    else:
        lines.append("- Repo path: not found")
    lines.append(f"- API URL: {status['server_url']}")
    lines.append(f"- Reachable: {'yes' if status['reachable'] else 'no'}")
    if status["last_sweep"]:
        lines.append(f"- Last sweep: {status['last_sweep']}")
    if status["next_sweep"]:
        lines.append(f"- Next sweep: {status['next_sweep']}")
    lines.append(f"- Sweep in progress: {'yes' if status['sweep_in_progress'] else 'no'}")
    lines.append(f"- Sources OK / failed: {status['sources_ok']} / {status['sources_failed']}")
    lines.append(
        f"- LLM ideas enabled: {'yes' if status['llm_enabled'] else 'no'}"
        + (f" ({status['llm_provider']})" if status.get("llm_provider") else "")
    )
    lines.append(f"- Idea count: {status['idea_count']}")
    if status["top_ideas"]:
        lines.append(f"- Top ideas: {', '.join(status['top_ideas'])}")
    latest_run = status.get("latest_run", {}) or {}
    if latest_run.get("latest_file"):
        lines.append(f"- Latest run file: {latest_run['latest_file']}")
        if latest_run.get("payload_preview"):
            lines.append(f"- Latest run preview: {latest_run['payload_preview']}")
    if not status["reachable"] and status["health_error"]:
        lines.append(f"- Health probe error: {status['health_error']}")
    return "\n".join(lines)


def crucix_launch_instructions() -> str:
    repo = resolve_crucix_repo_path()
    if repo is None:
        return (
            "Crucix repo not found. Configure crucix.repo_path to the local clone of "
            "https://github.com/calesthio/Crucix and ensure Node.js 22+ is installed."
        )
    return (
        f"Crucix repo: {repo}\n"
        "Start it with:\n"
        f"  cd \"{repo}\"\n"
        "  npm install\n"
        "  npm start\n\n"
        f"Expected API health endpoint: {crucix_server_url().rstrip('/')}/api/health"
    )


def start_crucix_backend(timeout: float = 12.0) -> dict:
    repo = resolve_crucix_repo_path()
    if repo is None:
        return {"started": False, "message": "Crucix repo not found."}

    node_cmd = shutil.which("node")
    if not node_cmd:
        return {"started": False, "message": "Node.js is not installed or not on PATH."}

    server_url = crucix_server_url().rstrip("/")
    already_live, _ = _http_json(f"{server_url}/api/health", timeout=1.5)
    if isinstance(already_live, dict) and already_live.get("status") == "ok":
        return {
            "started": True,
            "message": "Crucix backend is already running.",
            "server_url": server_url,
        }

    try:
        (repo / "runs").mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"started": False, "message": f"Crucix runtime directory setup failed: {exc}"}

    logs_dir = _bridge_logs_dir("crucix")
    log_path = logs_dir / "crucix.log"
    try:
        stdout_handle = open(log_path, "a", encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"started": False, "message": f"Could not open Crucix log file: {exc}"}

    command = [node_cmd, "server.mjs"]
    last_error = ""
    started = False
    for flags in _windows_creationflags():
        try:
            kwargs = {
                "cwd": str(repo),
                "stdout": stdout_handle,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
                "start_new_session": os.name != "nt",
                "env": _crucix_runtime_env(),
            }
            if os.name == "nt":
                kwargs["creationflags"] = flags
            subprocess.Popen(command, **kwargs)
            started = True
            break
        except Exception as exc:
            last_error = str(exc)
            continue

    if not started:
        stdout_handle.close()
        return {"started": False, "message": f"Crucix launch failed: {last_error}", "log_path": str(log_path)}

    deadline = time.time() + max(float(timeout or 0.0), 0.0)
    while time.time() < deadline:
        payload, _ = _http_json(f"{server_url}/api/health", timeout=1.5)
        if isinstance(payload, dict) and payload.get("status") == "ok":
            return {
                "started": True,
                "message": "Crucix backend started.",
                "server_url": server_url,
                "log_path": str(log_path),
            }
        time.sleep(0.6)

    return {
        "started": False,
        "message": "Crucix launch was attempted but the API did not become ready in time.",
        "server_url": server_url,
        "log_path": str(log_path),
    }
