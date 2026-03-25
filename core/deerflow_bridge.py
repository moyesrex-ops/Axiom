import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from core.runtime_config import load_runtime_config, update_runtime_config
from core.secret_config import get_gemini_api_key


DEFAULT_DEERFLOW_UI_URL = "http://127.0.0.1:2026"
DEFAULT_DEERFLOW_GATEWAY_URL = "http://127.0.0.1:8001"
DEFAULT_DEERFLOW_LANGGRAPH_URL = "http://127.0.0.1:2024"
AXIOM_DEERFLOW_MANAGED_MARKER = "# AXIOM-managed DeerFlow config"
MODELS_SECTION_PATTERN = re.compile(
    r"(?ms)^models:\r?\n.*?(?=^# ============================================================================\r?\n# Tool Groups Configuration)"
)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def configure_deerflow(updates: dict) -> dict:
    return update_runtime_config({"deerflow": updates or {}})


def _deerflow_config() -> dict:
    return load_runtime_config().get("deerflow", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return None


def _safe_json_get(url: str, timeout: float = 8.0) -> tuple[bool, dict]:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return True, payload if isinstance(payload, dict) else {}
    except Exception:
        return False, {}


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


def _read_text(path: Path, limit: int | None = None) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return raw[:limit].strip() if isinstance(limit, int) and limit > 0 else raw


def _count_skill_files(skills_root: Path) -> int:
    if not skills_root.exists():
        return 0
    try:
        return sum(1 for path in skills_root.rglob("SKILL.md") if path.is_file())
    except Exception:
        return 0


def _endpoint_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(str(url or "").strip().rstrip("/"))
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 80


def _gateway_url() -> str:
    cfg = _deerflow_config()
    value = (
        str(cfg.get("gateway_url", "") or "").strip()
        or str(cfg.get("url", "") or "").strip()
        or DEFAULT_DEERFLOW_UI_URL
    )
    return value.rstrip("/")


def _langgraph_url() -> str:
    cfg = _deerflow_config()
    configured = str(cfg.get("langgraph_url", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    gateway = _gateway_url().rstrip("/")
    if gateway == DEFAULT_DEERFLOW_UI_URL.rstrip("/"):
        return gateway + "/api/langgraph"
    return DEFAULT_DEERFLOW_LANGGRAPH_URL


def resolve_deerflow_repo_path() -> Path | None:
    cfg = _deerflow_config()
    runtime = load_runtime_config()
    candidates = [
        _path_or_none(cfg.get("repo_path", "")),
        _path_or_none((runtime.get("skill_library", {}) or {}).get("deerflow_path", "")),
        Path.home() / "deer-flow_upstream",
        Path.home() / "deer-flow",
        Path.home() / "Axiom_research" / "external" / "deer-flow",
    ]
    repo = _first_existing_path([path for path in candidates if path is not None])
    if repo is None:
        return None
    if (repo / "README.md").exists() and (repo / "backend" / "pyproject.toml").exists():
        return repo
    return None


def _deerflow_config_path(repo: Path | None) -> Path | None:
    return repo / "config.yaml" if repo else None


def _deerflow_env_path(repo: Path | None) -> Path | None:
    return repo / ".env" if repo else None


def _backend_venv_ready(repo: Path | None) -> bool:
    if repo is None:
        return False
    candidates = [
        repo / "backend" / ".venv" / "Scripts" / "python.exe",
        repo / "backend" / ".venv" / "bin" / "python",
        repo / "backend" / ".venv",
    ]
    return any(candidate.exists() for candidate in candidates)


def _frontend_node_modules_ready(repo: Path | None) -> bool:
    if repo is None:
        return False
    return (repo / "frontend" / "node_modules").exists()


def _is_managed_deerflow_config(config_path: Path | None) -> bool:
    if config_path is None or not config_path.exists():
        return False
    return AXIOM_DEERFLOW_MANAGED_MARKER in _read_text(config_path)


def _display_name_for_model(model_name: str) -> str:
    value = str(model_name or "").strip().replace("models/", "")
    if not value:
        return "Gemini"
    parts = []
    for chunk in value.replace("_", "-").split("-"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.isdigit() or "." in chunk:
            parts.append(chunk)
        else:
            parts.append(chunk.capitalize())
    return " ".join(parts) or "Gemini"


def _axiom_text_model_names() -> list[str]:
    runtime = load_runtime_config()
    text_models = runtime.get("text_models", {}) or {}
    ordered = [
        str(text_models.get("fast", "") or "").strip(),
        str(text_models.get("default", "") or "").strip(),
        str(text_models.get("reasoning", "") or "").strip(),
    ]
    unique: list[str] = []
    for name in ordered:
        if name and name not in unique:
            unique.append(name)
    if unique:
        return unique
    return ["gemini-2.5-flash", "gemini-2.5-pro"]


def _render_managed_models_block() -> str:
    lines = ["models:"]
    for model_name in _axiom_text_model_names():
        display_name = _display_name_for_model(model_name)
        lines.extend(
            [
                f"  - name: {model_name}",
                f"    display_name: {display_name}",
                "    use: langchain_google_genai:ChatGoogleGenerativeAI",
                f"    model: {model_name}",
                "    google_api_key: $GOOGLE_API_KEY",
                "    max_tokens: 8192",
                "    supports_vision: true",
            ]
        )
        normalized = model_name.lower()
        if "pro" in normalized or "thinking" in normalized:
            lines.append("    supports_thinking: true")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n\n"


def _render_managed_config(template_text: str) -> str:
    normalized = str(template_text or "").replace("\r\n", "\n")
    if MODELS_SECTION_PATTERN.search(normalized):
        updated = MODELS_SECTION_PATTERN.sub(_render_managed_models_block(), normalized, count=1)
    else:
        updated = _render_managed_models_block() + normalized
    if AXIOM_DEERFLOW_MANAGED_MARKER not in updated:
        updated = AXIOM_DEERFLOW_MANAGED_MARKER + "\n" + updated.lstrip()
    return updated


def ensure_deerflow_config(force: bool = False) -> dict:
    repo = resolve_deerflow_repo_path()
    if repo is None:
        return {"ok": False, "message": "DeerFlow repo was not found.", "config_path": ""}

    template_path = repo / "config.example.yaml"
    config_path = repo / "config.yaml"
    env_example = repo / ".env.example"
    env_path = repo / ".env"
    if not template_path.exists():
        return {
            "ok": False,
            "message": f"DeerFlow template config is missing at {template_path}.",
            "config_path": str(config_path),
        }

    created = False
    updated = False
    skipped = False
    try:
        template_text = template_path.read_text(encoding="utf-8", errors="replace")
        if config_path.exists():
            current_text = config_path.read_text(encoding="utf-8", errors="replace")
            managed = AXIOM_DEERFLOW_MANAGED_MARKER in current_text
            if managed or force:
                rendered = _render_managed_config(current_text or template_text)
                if rendered != current_text:
                    config_path.write_text(rendered, encoding="utf-8")
                    updated = True
            else:
                skipped = True
        else:
            config_path.write_text(_render_managed_config(template_text), encoding="utf-8")
            created = True
    except Exception as exc:
        return {
            "ok": False,
            "message": f"AXIOM could not create DeerFlow config.yaml: {exc}",
            "config_path": str(config_path),
        }

    env_created = False
    if env_example.exists() and not env_path.exists():
        try:
            shutil.copyfile(env_example, env_path)
            env_created = True
        except Exception:
            env_created = False

    message = "DeerFlow config is ready."
    if skipped:
        message = "DeerFlow config exists and was left unchanged because it is user-managed."
    elif created:
        message = "AXIOM created a managed Gemini-backed DeerFlow config."
    elif updated:
        message = "AXIOM refreshed its managed Gemini-backed DeerFlow config."

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "config_path": str(config_path),
        "env_path": str(env_path) if env_path.exists() else "",
        "env_created": env_created,
        "managed": _is_managed_deerflow_config(config_path),
        "message": message,
    }


def _ensure_headless_urls() -> dict:
    cfg = _deerflow_config()
    updates = {}
    if not str(cfg.get("gateway_url", "") or "").strip():
        updates["gateway_url"] = DEFAULT_DEERFLOW_GATEWAY_URL
    if not str(cfg.get("langgraph_url", "") or "").strip():
        updates["langgraph_url"] = DEFAULT_DEERFLOW_LANGGRAPH_URL
    if not updates:
        return load_runtime_config()
    return configure_deerflow(updates)


def _deerflow_process_env(repo: Path) -> dict:
    env = os.environ.copy()
    key = get_gemini_api_key()
    if key:
        env["GOOGLE_API_KEY"] = key
        env.setdefault("GEMINI_API_KEY", key)
    config_path = _deerflow_config_path(repo)
    if config_path and config_path.exists():
        env["DEER_FLOW_CONFIG_PATH"] = str(config_path)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("NO_COLOR", "1")
    return env


def _run_command(command: list[str], cwd: Path, env: dict, timeout: int) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(int(timeout or 0), 1),
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        excerpt = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()[:1600]
        return {"ok": False, "returncode": None, "excerpt": excerpt, "message": "Command timed out."}
    except Exception as exc:
        return {"ok": False, "returncode": None, "excerpt": "", "message": str(exc)}

    excerpt = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()[:1600]
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "excerpt": excerpt,
        "message": "ok" if result.returncode == 0 else f"Command exited with code {result.returncode}.",
    }


def _probe_langgraph(langgraph_url: str) -> tuple[bool, str]:
    try:
        response = requests.post(f"{langgraph_url.rstrip('/')}/threads", json={}, timeout=8)
        response.raise_for_status()
        payload = response.json() or {}
        thread_id = str(payload.get("thread_id", "") or "").strip()
        if thread_id:
            return True, ""
        return False, "LangGraph did not return a thread id."
    except Exception as exc:
        return False, str(exc)


def _launch_detached(command: list[str], cwd: Path, env: dict, log_path: Path) -> tuple[subprocess.Popen | None, str]:
    try:
        log_handle = open(log_path, "a", encoding="utf-8")
    except Exception as exc:
        return None, f"AXIOM could not open DeerFlow log file {log_path}: {exc}"

    process = None
    last_error = ""
    try:
        for creationflags in _windows_creationflags():
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(cwd),
                    env=env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                break
            except Exception as exc:
                last_error = str(exc)
    finally:
        try:
            log_handle.close()
        except Exception:
            pass
    return process, last_error


def collect_deerflow_status(limit: int = 5) -> dict:
    repo = resolve_deerflow_repo_path()
    gateway_url = _gateway_url()
    langgraph_url = _langgraph_url()
    cfg = _deerflow_config()
    reachable, health = _safe_json_get(f"{gateway_url}/health")

    models = {}
    skills = {}
    agents = {}
    if reachable:
        _, models = _safe_json_get(f"{gateway_url}/api/models")
        _, skills = _safe_json_get(f"{gateway_url}/api/skills")
        _, agents = _safe_json_get(f"{gateway_url}/api/agents")

    skills_root = repo / "skills" if repo else None
    config_path = _deerflow_config_path(repo)
    env_path = _deerflow_env_path(repo)
    service_mode = "full_stack" if gateway_url.rstrip("/") == DEFAULT_DEERFLOW_UI_URL.rstrip("/") else "headless"

    return {
        "repo_path": str(repo) if repo else "",
        "gateway_url": gateway_url,
        "langgraph_url": langgraph_url,
        "proxy_reachable": reachable,
        "health_status": str(health.get("status", "") or ""),
        "node_available": bool(shutil.which("node")),
        "uv_available": bool(shutil.which("uv")),
        "pnpm_available": bool(shutil.which("pnpm")),
        "auto_start": bool(cfg.get("auto_start", False)),
        "service_mode": service_mode,
        "config_path": str(config_path) if config_path and config_path.exists() else "",
        "env_path": str(env_path) if env_path and env_path.exists() else "",
        "managed_config": _is_managed_deerflow_config(config_path),
        "gemini_api_key_present": bool(get_gemini_api_key()),
        "backend_venv_ready": _backend_venv_ready(repo),
        "frontend_node_modules_ready": _frontend_node_modules_ready(repo),
        "skills_root": str(skills_root) if skills_root and skills_root.exists() else "",
        "local_skill_count": _count_skill_files(skills_root) if skills_root else 0,
        "models_count": len((models.get("models", []) or [])),
        "skills_count": len((skills.get("skills", []) or [])),
        "agents_count": len((agents.get("agents", []) or [])),
        "sample_models": [str(row.get("name", "")) for row in (models.get("models", []) or [])[: max(int(limit), 1)]],
        "sample_skills": [str(row.get("name", "")) for row in (skills.get("skills", []) or [])[: max(int(limit), 1)]],
        "sample_agents": [str(row.get("name", "")) for row in (agents.get("agents", []) or [])[: max(int(limit), 1)]],
    }


def format_deerflow_status(limit: int = 5) -> str:
    status = collect_deerflow_status(limit=limit)
    lines = [
        "DeerFlow integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Service mode: {status['service_mode']}",
        f"Auto-start: {'yes' if status['auto_start'] else 'no'}",
        f"Gateway URL: {status['gateway_url']}",
        f"LangGraph URL: {status['langgraph_url']}",
        f"Proxy reachable: {'yes' if status['proxy_reachable'] else 'no'}",
        f"Gemini API key available: {'yes' if status['gemini_api_key_present'] else 'no'}",
        f"Node available: {'yes' if status['node_available'] else 'no'}",
        f"uv available: {'yes' if status['uv_available'] else 'no'}",
        f"pnpm available: {'yes' if status['pnpm_available'] else 'no'}",
        f"Config file present: {'yes' if status['config_path'] else 'no'}",
        f"Managed config: {'yes' if status['managed_config'] else 'no'}",
        f"Backend venv ready: {'yes' if status['backend_venv_ready'] else 'no'}",
        f"Frontend deps ready: {'yes' if status['frontend_node_modules_ready'] else 'no'}",
        f"Local DeerFlow skills: {status['local_skill_count']}",
    ]
    if status["proxy_reachable"]:
        lines.extend(
            [
                f"Remote models: {status['models_count']}",
                f"Remote skills: {status['skills_count']}",
                f"Remote agents: {status['agents_count']}",
            ]
        )
        if status["sample_models"]:
            lines.append("Models: " + ", ".join(status["sample_models"]))
        if status["sample_skills"]:
            lines.append("Skills: " + ", ".join(status["sample_skills"]))
        if status["sample_agents"]:
            lines.append("Agents: " + ", ".join(status["sample_agents"]))
    return "\n".join(lines)


def deerflow_launch_instructions() -> str:
    status = collect_deerflow_status(limit=3)
    if not status["repo_path"]:
        return (
            "DeerFlow repo was not found. Clone it under C:/Users/moyes/deer-flow_upstream "
            "or set deerflow.repo_path in runtime.local.json."
        )
    if status["proxy_reachable"]:
        return (
            f"DeerFlow is already reachable at {status['gateway_url']}.\n"
            "Use deerflow_control with action='query' to send work into the harness."
        )
    return (
        "AXIOM can manage DeerFlow directly.\n"
        "Recommended path:\n"
        "1. deerflow_control action='prepare'\n"
        "2. deerflow_control action='start'\n"
        "3. deerflow_control action='query' prompt='<task>'\n\n"
        "AXIOM will generate a Gemini-backed config.yaml, inject GOOGLE_API_KEY from its own secret "
        "store, and launch DeerFlow headlessly through the local Gateway/LangGraph services."
    )


def prepare_deerflow_repo(timeout: int = 1800, install_frontend: bool = False) -> dict:
    repo = resolve_deerflow_repo_path()
    if repo is None:
        return {"prepared": False, "message": "DeerFlow repo was not found.", "repo_path": ""}

    config_result = ensure_deerflow_config()
    if not config_result.get("ok"):
        return {
            "prepared": False,
            "message": str(config_result.get("message", "DeerFlow config could not be prepared.")),
            "repo_path": str(repo),
            "config_path": str(config_result.get("config_path", "")),
        }

    _ensure_headless_urls()
    env = _deerflow_process_env(repo)
    if not env.get("GOOGLE_API_KEY"):
        return {
            "prepared": False,
            "message": "Gemini API key is missing. Set GEMINI_API_KEY or GOOGLE_API_KEY for AXIOM first.",
            "repo_path": str(repo),
            "config_path": str(config_result.get("config_path", "")),
        }
    if not shutil.which("uv"):
        return {
            "prepared": False,
            "message": "uv is not available on this machine, so DeerFlow backend dependencies cannot be prepared.",
            "repo_path": str(repo),
            "config_path": str(config_result.get("config_path", "")),
        }

    remaining = max(int(timeout or 0), 60)
    backend_result = _run_command(["uv", "sync"], cwd=repo / "backend", env=env, timeout=min(remaining, 1500))
    remaining = max(remaining - min(remaining, 1500), 60)
    frontend_result = {"ok": True, "skipped": True, "message": "Frontend install skipped.", "excerpt": ""}

    if install_frontend:
        if not shutil.which("pnpm"):
            frontend_result = {
                "ok": False,
                "skipped": False,
                "message": "pnpm is not available, so DeerFlow frontend dependencies cannot be prepared.",
                "excerpt": "",
            }
        else:
            frontend_result = _run_command(
                ["pnpm", "install"],
                cwd=repo / "frontend",
                env=env,
                timeout=min(remaining, 1500),
            )
            frontend_result["skipped"] = False

    current = collect_deerflow_status(limit=3)
    prepared = bool(backend_result.get("ok")) and bool(current.get("backend_venv_ready"))
    if install_frontend:
        prepared = prepared and bool(frontend_result.get("ok")) and bool(current.get("frontend_node_modules_ready"))

    message = "DeerFlow backend is prepared."
    if install_frontend:
        message = "DeerFlow backend and frontend are prepared." if prepared else "DeerFlow prepare completed with issues."
    elif not prepared:
        message = "DeerFlow backend prepare completed with issues."

    return {
        "prepared": prepared,
        "message": message,
        "repo_path": str(repo),
        "config_path": str(config_result.get("config_path", "")),
        "gateway_url": current.get("gateway_url", ""),
        "langgraph_url": current.get("langgraph_url", ""),
        "backend": backend_result,
        "frontend": frontend_result,
    }


def start_deerflow_backend(timeout: float = 40.0) -> dict:
    status = collect_deerflow_status(limit=3)
    if status["proxy_reachable"]:
        return {
            "started": True,
            "already_running": True,
            "gateway_url": status["gateway_url"],
            "langgraph_url": status["langgraph_url"],
            "message": "DeerFlow gateway is already reachable.",
        }

    repo = resolve_deerflow_repo_path()
    if repo is None:
        return {"started": False, "message": "DeerFlow repo was not found.", "repo_path": ""}

    config_result = ensure_deerflow_config()
    if not config_result.get("ok"):
        return {
            "started": False,
            "message": str(config_result.get("message", "DeerFlow config is not ready.")),
            "repo_path": str(repo),
        }
    _ensure_headless_urls()
    status = collect_deerflow_status(limit=3)

    env = _deerflow_process_env(repo)
    if not env.get("GOOGLE_API_KEY"):
        return {
            "started": False,
            "message": "Gemini API key is missing. Set GEMINI_API_KEY or GOOGLE_API_KEY for AXIOM first.",
            "repo_path": str(repo),
            "config_path": str(config_result.get("config_path", "")),
        }
    if not shutil.which("uv"):
        return {
            "started": False,
            "message": "uv is not available on this machine, so AXIOM cannot launch DeerFlow.",
            "repo_path": str(repo),
        }

    gateway_host, gateway_port = _endpoint_host_port(status["gateway_url"])
    logs_dir = _bridge_logs_dir("deerflow")
    langgraph_log = logs_dir / "langgraph.log"
    gateway_log = logs_dir / "gateway.log"

    langgraph_process, langgraph_error = _launch_detached(
        ["uv", "run", "langgraph", "dev", "--no-browser", "--allow-blocking"],
        cwd=repo / "backend",
        env=env,
        log_path=langgraph_log,
    )
    if langgraph_process is None:
        return {
            "started": False,
            "message": f"Failed to launch DeerFlow LangGraph server: {langgraph_error}",
            "repo_path": str(repo),
            "log_path": str(langgraph_log),
        }

    gateway_process, gateway_error = _launch_detached(
        [
            "uv",
            "run",
            "uvicorn",
            "app.gateway.app:app",
            "--host",
            gateway_host,
            "--port",
            str(gateway_port),
        ],
        cwd=repo / "backend",
        env=env,
        log_path=gateway_log,
    )
    if gateway_process is None:
        return {
            "started": False,
            "message": f"Failed to launch DeerFlow gateway: {gateway_error}",
            "repo_path": str(repo),
            "log_path": str(gateway_log),
            "langgraph_log": str(langgraph_log),
        }

    deadline = time.time() + max(float(timeout or 0), 5.0)
    langgraph_error_text = ""
    while time.time() < deadline:
        current = collect_deerflow_status(limit=3)
        if current["proxy_reachable"]:
            langgraph_ok, langgraph_error_text = _probe_langgraph(current["langgraph_url"])
            if langgraph_ok:
                return {
                    "started": True,
                    "gateway_pid": gateway_process.pid,
                    "langgraph_pid": langgraph_process.pid,
                    "gateway_url": current["gateway_url"],
                    "langgraph_url": current["langgraph_url"],
                    "gateway_log": str(gateway_log),
                    "langgraph_log": str(langgraph_log),
                    "message": "DeerFlow launched successfully in managed headless mode.",
                }
        if gateway_process.poll() is not None and langgraph_process.poll() is not None:
            break
        time.sleep(0.75)

    return {
        "started": False,
        "gateway_pid": gateway_process.pid,
        "langgraph_pid": langgraph_process.pid,
        "gateway_url": status["gateway_url"],
        "langgraph_url": status["langgraph_url"],
        "gateway_log": str(gateway_log),
        "langgraph_log": str(langgraph_log),
        "message": "DeerFlow launch was attempted but the managed endpoints never became fully ready.",
        "langgraph_error": langgraph_error_text,
        "gateway_log_excerpt": _read_text(gateway_log, limit=900),
        "langgraph_log_excerpt": _read_text(langgraph_log, limit=900),
    }


def _mode_context(mode: str) -> dict:
    normalized = str(mode or "pro").strip().lower()
    mapping = {
        "flash": {"thinking_enabled": False, "is_plan_mode": False, "subagent_enabled": False},
        "standard": {"thinking_enabled": True, "is_plan_mode": False, "subagent_enabled": False},
        "pro": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": False},
        "ultra": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": True},
    }
    return mapping.get(normalized, mapping["pro"])


def _iter_sse_events(response) -> list[dict]:
    events = []
    current_event = "message"
    data_lines: list[str] = []

    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue
        line = str(raw_line).rstrip("\r")
        if not line:
            if data_lines:
                events.append({"event": current_event, "data": "\n".join(data_lines)})
            current_event = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        events.append({"event": current_event, "data": "\n".join(data_lines)})
    return events


def _extract_content_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = str(item.get("text", "") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        return str(content.get("text", "") or content.get("content", "") or "").strip()
    return ""


def _extract_ai_text_from_values(payload: dict) -> str:
    messages = payload.get("messages", []) or []
    ai_messages = []
    for message in messages:
        message_type = str(message.get("type", "") or message.get("role", "") or "").strip().lower()
        if message_type not in {"ai", "assistant"}:
            continue
        text = _extract_content_text(message.get("content", ""))
        if text:
            ai_messages.append(text)
    return ai_messages[-1] if ai_messages else ""


def run_deerflow_query(prompt: str, mode: str = "pro", thread_id: str = "", timeout: int = 240) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "Please provide a prompt for DeerFlow."}

    status = collect_deerflow_status(limit=3)
    if not status["proxy_reachable"] and status.get("auto_start"):
        start_deerflow_backend(timeout=min(max(int(timeout or 0), 20), 45))
        status = collect_deerflow_status(limit=3)

    if not status["proxy_reachable"]:
        return {
            "ok": False,
            "message": (
                f"DeerFlow is not reachable at {status['gateway_url']}. "
                "Run deerflow_control with action='prepare' or action='start' first."
            ),
            "thread_id": "",
        }

    resolved_thread_id = str(thread_id or "").strip()
    langgraph_url = status["langgraph_url"]
    if not resolved_thread_id:
        try:
            response = requests.post(f"{langgraph_url}/threads", json={}, timeout=20)
            response.raise_for_status()
            payload = response.json() or {}
            resolved_thread_id = str(payload.get("thread_id", "") or "").strip()
        except Exception as error:
            return {
                "ok": False,
                "message": f"DeerFlow thread creation failed: {error}",
                "thread_id": "",
            }
    if not resolved_thread_id:
        return {"ok": False, "message": "DeerFlow did not return a thread id.", "thread_id": ""}

    payload = {
        "assistant_id": "lead_agent",
        "input": {
            "messages": [
                {
                    "type": "human",
                    "content": [{"type": "text", "text": prompt}],
                }
            ]
        },
        "stream_mode": ["values", "messages-tuple"],
        "stream_subgraphs": True,
        "config": {"recursion_limit": 1000},
        "context": {**_mode_context(mode), "thread_id": resolved_thread_id},
    }

    try:
        response = requests.post(
            f"{langgraph_url}/threads/{resolved_thread_id}/runs/stream",
            json=payload,
            stream=True,
            timeout=(20, int(timeout)),
        )
        response.raise_for_status()
    except Exception as error:
        return {
            "ok": False,
            "message": f"DeerFlow run failed to start: {error}",
            "thread_id": resolved_thread_id,
        }

    run_id = ""
    final_text = ""
    events = []
    try:
        for event in _iter_sse_events(response):
            events.append(event)
            event_type = event.get("event", "")
            data = event.get("data", "")
            if event_type == "metadata":
                try:
                    metadata = json.loads(data)
                    run_id = str(metadata.get("run_id", "") or run_id)
                except Exception:
                    pass
            elif event_type == "values":
                try:
                    values = json.loads(data)
                    candidate = _extract_ai_text_from_values(values)
                    if candidate:
                        final_text = candidate
                except Exception:
                    continue
    finally:
        response.close()

    if not final_text:
        return {
            "ok": False,
            "message": "DeerFlow completed without a readable AI response.",
            "thread_id": resolved_thread_id,
            "run_id": run_id,
        }

    return {
        "ok": True,
        "thread_id": resolved_thread_id,
        "run_id": run_id,
        "mode": str(mode or "pro").strip().lower(),
        "response_text": final_text,
        "events_count": len(events),
    }
