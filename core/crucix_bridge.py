import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from core.runtime_config import load_runtime_config, update_runtime_config


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
        "idea_count": len(ideas),
        "top_ideas": [str(item.get("title", "") or "").strip() for item in ideas[:3] if isinstance(item, dict)],
        "latest_run": latest_snapshot,
        "dashboard_data_preview": _truncate(json.dumps(data_dict, ensure_ascii=False), 500) if data_dict else "",
    }


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
    lines.append(f"- LLM ideas enabled: {'yes' if status['llm_enabled'] else 'no'}")
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
    server_url = crucix_server_url().rstrip("/")
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
