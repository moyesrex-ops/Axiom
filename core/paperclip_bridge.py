import json
import shutil
import socket
from pathlib import Path
from urllib.parse import urlparse

from core.runtime_config import load_runtime_config, update_runtime_config


def configure_paperclip(updates: dict) -> dict:
    updates = updates or {}
    merged = {"paperclip": updates}
    repo_path = str(updates.get("repo_path", "") or "").strip()
    if repo_path:
        merged["skill_library"] = {"paperclip_path": repo_path}
        merged["agent_library"] = {"paperclip_path": repo_path}
    return update_runtime_config(merged)


def _paperclip_config() -> dict:
    return load_runtime_config().get("paperclip", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    runtime = load_runtime_config()
    configured = _path_or_none(_paperclip_config().get("repo_path", ""))
    skill_path = _path_or_none((runtime.get("skill_library", {}) or {}).get("paperclip_path", ""))
    agent_path = _path_or_none((runtime.get("agent_library", {}) or {}).get("paperclip_path", ""))
    return [
        path
        for path in [
            configured,
            skill_path,
            agent_path,
            Path.home() / "Axiom_research" / "external" / "paperclip",
        ]
        if path is not None
    ]


def resolve_paperclip_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "package.json").exists() and (candidate / "README.md").exists():
                return candidate
        except Exception:
            continue
    return None


def _parse_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(str(url or "").strip())
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 80


def _is_tcp_reachable(url: str, timeout: float = 0.35) -> bool:
    try:
        host, port = _parse_host_port(url)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _read_text(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def _count_files(root: Path | None, glob_pattern: str) -> int:
    if root is None or not root.exists():
        return 0
    try:
        return sum(1 for item in root.glob(glob_pattern) if item.is_file())
    except Exception:
        return 0


def collect_paperclip_status() -> dict:
    repo = resolve_paperclip_repo_path()
    package_json = _read_json(repo / "package.json") if repo else {}
    cfg = _paperclip_config()
    api_url = str(cfg.get("api_url", "http://127.0.0.1:3100") or "http://127.0.0.1:3100").strip()
    return {
        "repo_path": str(repo) if repo else "",
        "api_url": api_url,
        "api_reachable": bool(api_url) and _is_tcp_reachable(api_url),
        "auto_start": bool(cfg.get("auto_start", False)),
        "node_available": bool(shutil.which("node")),
        "pnpm_available": bool(shutil.which("pnpm")),
        "package_name": str(package_json.get("name", "") or "").strip(),
        "package_version": str(package_json.get("version", "") or "").strip(),
        "skills_count": _count_files((repo / "skills") if repo else None, "**/SKILL.md"),
        "agents_docs_count": _count_files(repo, "**/AGENTS.md") if repo else 0,
        "ui_present": bool(repo and (repo / "ui").exists()),
        "server_present": bool(repo and (repo / "server").exists()),
        "readme_excerpt": _read_text(repo / "README.md", limit=1100) if repo else "",
    }


def format_paperclip_status() -> str:
    status = collect_paperclip_status()
    lines = [
        "Paperclip integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"API URL: {status['api_url']}",
        f"API reachable: {'yes' if status['api_reachable'] else 'no'}",
        f"Auto-start: {'enabled' if status['auto_start'] else 'disabled'}",
        f"Node available: {'yes' if status['node_available'] else 'no'}",
        f"pnpm available: {'yes' if status['pnpm_available'] else 'no'}",
        f"Package: {status['package_name'] or 'unknown'} {status['package_version'] or ''}".strip(),
        f"Paperclip skills: {status['skills_count']}",
        f"AGENTS docs: {status['agents_docs_count']}",
        f"UI present: {'yes' if status['ui_present'] else 'no'}",
        f"Server present: {'yes' if status['server_present'] else 'no'}",
    ]
    return "\n".join(lines)


def paperclip_launch_instructions() -> str:
    status = collect_paperclip_status()
    if not status["repo_path"]:
        return (
            "Paperclip repo path is not configured. Set paperclip.repo_path or place the repo at "
            "C:/Users/moyes/Axiom_research/external/paperclip."
        )

    if not status["node_available"] or not status["pnpm_available"]:
        return (
            "Paperclip is cloned but Node.js or pnpm is missing. Install Node.js 20+ and pnpm, then run:\n"
            f"Set-Location '{status['repo_path']}'; pnpm install; pnpm dev"
        )

    return (
        "Paperclip is ready as an optional control-plane runtime. Typical commands:\n"
        f"Set-Location '{status['repo_path']}'; pnpm install\n"
        f"Set-Location '{status['repo_path']}'; pnpm test:run\n"
        f"Set-Location '{status['repo_path']}'; pnpm dev\n"
        f"API default: {status['api_url']}"
    )
