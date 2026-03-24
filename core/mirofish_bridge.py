import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from core.runtime_config import load_runtime_config, update_runtime_config


DEFAULT_MIROFISH_URL = "http://127.0.0.1:5001"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def configure_mirofish(updates: dict) -> dict:
    return update_runtime_config({"integrations": updates or {}})


def _integration_config() -> dict:
    return load_runtime_config().get("integrations", {}) or {}


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


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    cfg = _integration_config()
    home = Path.home()
    return [
        path
        for path in [
            _path_or_none(cfg.get("mirofish_path", "")),
            BASE_DIR / "research" / "MiroFish",
            home / "MiroFish",
            home / "MiroFish_upstream",
        ]
        if path is not None
    ]


def resolve_mirofish_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if not candidate.exists():
                continue
            if (candidate / "backend" / "run.py").exists():
                return candidate
            if (candidate / "run.py").exists() and (candidate / "app").exists():
                return candidate
        except Exception:
            continue
    return None


def mirofish_server_url() -> str:
    cfg = _integration_config()
    return str(cfg.get("mirofish_url", "") or DEFAULT_MIROFISH_URL).strip() or DEFAULT_MIROFISH_URL


def _backend_dir(repo_path: Path | None) -> Path | None:
    if repo_path is None:
        return None
    if (repo_path / "backend" / "run.py").exists():
        return repo_path / "backend"
    if (repo_path / "run.py").exists():
        return repo_path
    return None


def _uploads_dir(repo_path: Path | None) -> Path | None:
    backend = _backend_dir(repo_path)
    if backend is None:
        return None
    uploads = backend / "uploads"
    return uploads if uploads.exists() else uploads


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_text(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def _truncate(text: str, limit: int = 240) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _file_timestamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def _list_recent_dirs(root: Path | None, meta_filename: str) -> list[tuple[Path, dict]]:
    if root is None or not root.exists():
        return []

    items: list[tuple[Path, dict]] = []
    for child in root.iterdir():
        meta_path = child / meta_filename
        if not child.is_dir() or not meta_path.exists():
            continue
        payload = _read_json(meta_path)
        if not isinstance(payload, dict):
            continue
        items.append((child, payload))

    items.sort(key=lambda item: _file_timestamp(item[0] / meta_filename), reverse=True)
    return items


def list_mirofish_projects(limit: int = 5) -> list[dict]:
    repo = resolve_mirofish_repo_path()
    uploads = _uploads_dir(repo)
    items = _list_recent_dirs((uploads / "projects") if uploads else None, "project.json")
    rows = []
    for project_dir, payload in items[: max(int(limit), 1)]:
        rows.append(
            {
                "project_id": payload.get("project_id") or project_dir.name,
                "name": payload.get("name", "Unnamed Project"),
                "status": payload.get("status", "unknown"),
                "graph_id": payload.get("graph_id", ""),
                "files_count": len(payload.get("files", []) or []),
                "created_at": payload.get("created_at", ""),
                "updated_at": payload.get("updated_at", ""),
                "analysis_summary": _truncate(payload.get("analysis_summary", ""), 220),
            }
        )
    return rows


def list_mirofish_simulations(limit: int = 5) -> list[dict]:
    repo = resolve_mirofish_repo_path()
    uploads = _uploads_dir(repo)
    items = _list_recent_dirs((uploads / "simulations") if uploads else None, "state.json")
    rows = []
    for sim_dir, payload in items[: max(int(limit), 1)]:
        rows.append(
            {
                "simulation_id": payload.get("simulation_id") or sim_dir.name,
                "project_id": payload.get("project_id", ""),
                "graph_id": payload.get("graph_id", ""),
                "status": payload.get("status", "unknown"),
                "current_round": payload.get("current_round", 0),
                "profiles_count": payload.get("profiles_count", 0),
                "twitter_status": payload.get("twitter_status", ""),
                "reddit_status": payload.get("reddit_status", ""),
                "created_at": payload.get("created_at", ""),
                "updated_at": payload.get("updated_at", ""),
                "error": _truncate(payload.get("error", ""), 160),
            }
        )
    return rows


def list_mirofish_reports(limit: int = 5) -> list[dict]:
    repo = resolve_mirofish_repo_path()
    uploads = _uploads_dir(repo)
    items = _list_recent_dirs((uploads / "reports") if uploads else None, "meta.json")
    rows = []
    for report_dir, payload in items[: max(int(limit), 1)]:
        report_id = payload.get("report_id") or report_dir.name
        markdown_excerpt = _read_text(report_dir / "full_report.md", limit=500)
        rows.append(
            {
                "report_id": report_id,
                "simulation_id": payload.get("simulation_id", ""),
                "graph_id": payload.get("graph_id", ""),
                "status": payload.get("status", "unknown"),
                "created_at": payload.get("created_at", ""),
                "updated_at": payload.get("updated_at", ""),
                "error": _truncate(payload.get("error", ""), 160),
                "markdown_excerpt": _truncate(markdown_excerpt, 220),
            }
        )
    return rows


def _http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 2.5) -> tuple[dict | None, str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    try:
        req = urlrequest.Request(url, data=data, headers=headers, method=method.upper())
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        if not raw.strip():
            return {}, ""
        return json.loads(raw), ""
    except urlerror.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except urlerror.URLError as exc:
        return None, str(exc.reason or exc)
    except Exception as exc:
        return None, str(exc)


def mirofish_health() -> dict:
    base_url = mirofish_server_url().rstrip("/")
    payload, error_text = _http_json(f"{base_url}/health")
    reachable = bool(isinstance(payload, dict) and payload.get("status") == "ok")
    return {
        "server_url": base_url,
        "reachable": reachable,
        "error": "" if reachable else error_text,
        "payload": payload or {},
    }


def _detect_python_executable(repo_path: Path | None) -> str:
    candidates: list[Path] = []
    backend = _backend_dir(repo_path)
    if backend is not None:
        candidates.extend(
            [
                backend / ".venv" / "Scripts" / "python.exe",
                backend / ".venv" / "bin" / "python",
            ]
        )
    if repo_path is not None:
        candidates.extend(
            [
                repo_path / ".venv" / "Scripts" / "python.exe",
                repo_path / ".venv" / "bin" / "python",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _env_key_present(env_path: Path, key: str) -> bool:
    try:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=", re.IGNORECASE)
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if pattern.search(line):
                return True
    except Exception:
        pass
    return False


def start_mirofish_backend(timeout: float = 10.0) -> dict:
    repo = resolve_mirofish_repo_path()
    if repo is None:
        return {"started": False, "message": "MiroFish repo was not found."}

    health = mirofish_health()
    if health["reachable"]:
        return {
            "started": True,
            "already_running": True,
            "server_url": health["server_url"],
            "message": "MiroFish backend is already running.",
        }

    backend = _backend_dir(repo)
    if backend is None:
        return {"started": False, "message": "MiroFish backend entrypoint was not found."}

    run_py = backend / "run.py"
    if not run_py.exists():
        return {"started": False, "message": f"Missing backend entrypoint: {run_py}"}

    python_exe = _detect_python_executable(repo)
    log_path = _bridge_logs_dir("mirofish") / "backend.log"
    try:
        log_handle = open(log_path, "a", encoding="utf-8")
    except Exception as exc:
        return {
            "started": False,
            "server_url": mirofish_server_url(),
            "log_path": str(log_path),
            "message": f"AXIOM could not open the MiroFish bridge log: {exc}",
        }
    env = os.environ.copy()
    env["FLASK_DEBUG"] = "false"
    env["MIROFISH_LOG_DIR"] = str(log_path.parent)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    process = None
    last_error = None
    try:
        for creationflags in _windows_creationflags():
            try:
                process = subprocess.Popen(
                    [python_exe, str(run_py)],
                    cwd=str(backend),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                    env=env,
                )
                break
            except Exception as exc:
                last_error = exc
    finally:
        try:
            log_handle.close()
        except Exception:
            pass
    if process is None:
        return {"started": False, "message": f"Failed to launch MiroFish backend: {last_error}"}

    deadline = time.time() + max(float(timeout or 0), 1.0)
    while time.time() < deadline:
        health = mirofish_health()
        if health["reachable"]:
            return {
                "started": True,
                "pid": process.pid,
                "server_url": health["server_url"],
                "log_path": str(log_path),
                "message": "MiroFish backend launched successfully.",
            }
        if process.poll() is not None:
            break
        time.sleep(0.5)

    tail = _truncate(_read_text(log_path, limit=700), 320)
    return {
        "started": False,
        "pid": process.pid,
        "server_url": mirofish_server_url(),
        "log_path": str(log_path),
        "message": "MiroFish launch was attempted but the health check never passed.",
        "log_excerpt": tail,
    }


def _read_seed_profiles(repo_path: Path | None) -> tuple[list[dict], list[dict]]:
    if repo_path is None:
        return [], []

    backend = _backend_dir(repo_path)
    if backend is None:
        return [], []

    twitter_rows: list[dict] = []
    twitter_path = backend / "trading_twitter_profiles.csv"
    if twitter_path.exists():
        for line in twitter_path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
            parts = line.split(",", 3)
            if len(parts) < 4:
                continue
            twitter_rows.append(
                {
                    "entity_name": parts[0].strip(),
                    "bio": parts[1].strip(),
                    "personality": parts[2].strip(),
                    "interests": parts[3].strip(),
                    "platform": "twitter",
                }
            )

    reddit_rows: list[dict] = []
    reddit_path = backend / "trading_reddit_profiles.json"
    payload = _read_json(reddit_path) if reddit_path.exists() else None
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            reddit_rows.append(
                {
                    "entity_name": str(item.get("username", "")).strip(),
                    "bio": str(item.get("bio", "")).strip(),
                    "personality": str(item.get("personality", "")).strip(),
                    "interests": ", ".join(item.get("interests", []) or []),
                    "platform": "reddit",
                }
            )

    return twitter_rows, reddit_rows


def _market_keywords(asset: str) -> set[str]:
    value = str(asset or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", value))
    if "bitcoin" in value or "btc" in tokens:
        tokens.update({"bitcoin", "btc", "crypto", "ethereum", "defi", "memecoins"})
    if "gold" in value or "xau" in tokens:
        tokens.update({"gold", "inflation", "rates", "fed", "safe havens", "commodities"})
    if "eurusd" in value or ("eur" in tokens and "usd" in tokens):
        tokens.update({"forex", "eur", "usd", "currency", "central banks", "geopolitics"})
    if "usd" in tokens:
        tokens.update({"fed", "rates", "inflation"})
    if "spy" in tokens or "qqq" in tokens or "stocks" in tokens or "equity" in tokens:
        tokens.update({"tech", "growth", "value", "earnings", "fed", "market"})
    return {token for token in tokens if token}


def _score_text(text: str, keywords: set[str]) -> int:
    haystack = str(text or "").lower()
    score = 0
    for keyword in keywords:
        if keyword and keyword in haystack:
            score += 1
    return score


def _best_report_excerpt(repo_path: Path | None, asset: str) -> str:
    keywords = _market_keywords(asset)
    best_score = 0
    best_excerpt = ""
    for item in list_mirofish_reports(limit=12):
        excerpt = str(item.get("markdown_excerpt", "")).strip()
        score = _score_text(excerpt, keywords) + _score_text(item.get("simulation_id", ""), keywords)
        if score > best_score and excerpt:
            best_score = score
            best_excerpt = excerpt
    return best_excerpt


def get_mirofish_market_context(asset: str, limit: int = 6) -> dict:
    repo = resolve_mirofish_repo_path()
    backend = _backend_dir(repo)
    health = mirofish_health()
    twitter_rows, reddit_rows = _read_seed_profiles(repo)
    keywords = _market_keywords(asset)

    seed_config = _read_json(backend / "market_prediction_config.json") if backend else None
    matching_profiles = []
    for row in twitter_rows + reddit_rows:
        combined = " ".join(
            [
                str(row.get("entity_name", "")),
                str(row.get("bio", "")),
                str(row.get("personality", "")),
                str(row.get("interests", "")),
            ]
        )
        score = _score_text(combined, keywords)
        if score > 0:
            matching_profiles.append((score, row))
    matching_profiles.sort(key=lambda item: item[0], reverse=True)

    matching_posts = []
    if isinstance(seed_config, dict):
        for post in (seed_config.get("event_config", {}) or {}).get("initial_posts", []) or []:
            score = _score_text(post.get("content", ""), keywords)
            if score > 0:
                matching_posts.append((score, post))
        matching_posts.sort(key=lambda item: item[0], reverse=True)

    return {
        "available": bool(repo),
        "repo_path": str(repo) if repo else "",
        "backend_reachable": bool(health.get("reachable")),
        "seed_description": str((seed_config or {}).get("description", "")).strip() if isinstance(seed_config, dict) else "",
        "matching_profiles": [row for _, row in matching_profiles[: max(int(limit), 1)]],
        "matching_posts": [row for _, row in matching_posts[:3]],
        "report_excerpt": _best_report_excerpt(repo, asset),
    }


def format_mirofish_market_context(asset: str, limit: int = 6) -> str:
    context = get_mirofish_market_context(asset, limit=limit)
    if not context["available"]:
        return "MiroFish market context is unavailable because the repo was not found."

    lines = [f"MiroFish market context for {asset}"]
    lines.append(f"Repo: {context['repo_path']}")
    lines.append(f"Backend reachable: {'yes' if context['backend_reachable'] else 'no'}")
    if context["seed_description"]:
        lines.append(f"Seed scenario: {_truncate(context['seed_description'], 200)}")
    profiles = context.get("matching_profiles", [])
    if profiles:
        lines.append("Matching personas:")
        for row in profiles:
            lines.append(
                f"- {row.get('entity_name', 'unknown')} [{row.get('platform', 'seed')}]: "
                f"{_truncate(row.get('bio', ''), 120)} | interests={_truncate(row.get('interests', ''), 90)}"
            )
    posts = context.get("matching_posts", [])
    if posts:
        lines.append("Relevant seed posts:")
        for row in posts:
            lines.append(f"- {_truncate(row.get('content', ''), 160)}")
    excerpt = str(context.get("report_excerpt", "")).strip()
    if excerpt:
        lines.append(f"Latest matching report excerpt: {_truncate(excerpt, 220)}")
    return "\n".join(lines)


def collect_mirofish_status(limit: int = 5) -> dict:
    repo = resolve_mirofish_repo_path()
    backend = _backend_dir(repo)
    uploads = _uploads_dir(repo)
    health = mirofish_health()
    env_path = repo / ".env" if repo else None
    twitter_rows, reddit_rows = _read_seed_profiles(repo)

    projects = list_mirofish_projects(limit=limit)
    simulations = list_mirofish_simulations(limit=limit)
    reports = list_mirofish_reports(limit=limit)

    return {
        "repo_path": str(repo) if repo else "",
        "backend_path": str(backend) if backend else "",
        "uploads_path": str(uploads) if uploads else "",
        "server_url": health["server_url"],
        "backend_reachable": bool(health["reachable"]),
        "backend_error": str(health.get("error", "") or "").strip(),
        "env_path": str(env_path) if env_path and env_path.exists() else "",
        "llm_env_present": bool(env_path and env_path.exists() and _env_key_present(env_path, "LLM_API_KEY")),
        "zep_env_present": bool(env_path and env_path.exists() and _env_key_present(env_path, "ZEP_API_KEY")),
        "python_executable": _detect_python_executable(repo),
        "seed_description": str((_read_json(backend / "market_prediction_config.json") or {}).get("description", "")).strip() if backend else "",
        "twitter_seed_count": len(twitter_rows),
        "reddit_seed_count": len(reddit_rows),
        "projects_count": len(_list_recent_dirs((uploads / "projects") if uploads else None, "project.json")),
        "simulations_count": len(_list_recent_dirs((uploads / "simulations") if uploads else None, "state.json")),
        "reports_count": len(_list_recent_dirs((uploads / "reports") if uploads else None, "meta.json")),
        "recent_projects": projects,
        "recent_simulations": simulations,
        "recent_reports": reports,
    }


def format_mirofish_status(limit: int = 4) -> str:
    status = collect_mirofish_status(limit=limit)
    lines = [
        "MiroFish integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Backend path: {status['backend_path'] or 'not found'}",
        f"Server URL: {status['server_url']}",
        f"Backend reachable: {'yes' if status['backend_reachable'] else 'no'}",
        f"Python executable: {status['python_executable']}",
        f".env present: {'yes' if status['env_path'] else 'no'}",
        f"LLM key configured in .env: {'yes' if status['llm_env_present'] else 'no'}",
        f"Zep key configured in .env: {'yes' if status['zep_env_present'] else 'no'}",
        f"Twitter seed personas: {status['twitter_seed_count']}",
        f"Reddit seed personas: {status['reddit_seed_count']}",
        f"Projects on disk: {status['projects_count']}",
        f"Simulations on disk: {status['simulations_count']}",
        f"Reports on disk: {status['reports_count']}",
    ]
    if status["seed_description"]:
        lines.append(f"Seed scenario: {_truncate(status['seed_description'], 220)}")
    if status["backend_error"]:
        lines.append(f"Backend error: {_truncate(status['backend_error'], 160)}")
    if status["recent_projects"]:
        lines.append("Recent projects:")
        for item in status["recent_projects"]:
            lines.append(
                f"- {item['project_id']} [{item['status']}] "
                f"name={_truncate(item['name'], 40)} graph={item['graph_id'] or 'none'}"
            )
    if status["recent_simulations"]:
        lines.append("Recent simulations:")
        for item in status["recent_simulations"]:
            lines.append(
                f"- {item['simulation_id']} [{item['status']}] "
                f"project={item['project_id'] or 'unknown'} round={item['current_round']}"
            )
    if status["recent_reports"]:
        lines.append("Recent reports:")
        for item in status["recent_reports"]:
            lines.append(
                f"- {item['report_id']} [{item['status']}] "
                f"simulation={item['simulation_id'] or 'unknown'}"
            )
    return "\n".join(lines)


def mirofish_launch_instructions() -> str:
    repo = resolve_mirofish_repo_path()
    if repo is None:
        return (
            "MiroFish repo path is not configured. Set integrations.mirofish_path "
            "or place the repo at C:/Users/moyes/MiroFish."
        )

    backend = _backend_dir(repo)
    if backend is None:
        return "MiroFish backend entrypoint was not found."

    python_exe = _detect_python_executable(repo)
    return (
        "Launch MiroFish from PowerShell with:\n"
        f"Set-Location '{backend}'; '{python_exe}' run.py\n\n"
        f"Health check: {mirofish_server_url().rstrip('/')}/health"
    )
