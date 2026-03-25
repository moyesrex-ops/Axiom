import json
import shutil
from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config


def configure_lossless_claw(updates: dict) -> dict:
    updates = updates or {}
    merged = {"lossless_claw": updates}
    repo_path = str(updates.get("repo_path", "") or "").strip()
    if repo_path:
        merged["agent_library"] = {"lossless_claw_path": repo_path}
    return update_runtime_config(merged)


def _lossless_claw_config() -> dict:
    return load_runtime_config().get("lossless_claw", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    runtime = load_runtime_config()
    configured = _path_or_none(_lossless_claw_config().get("repo_path", ""))
    agent_path = _path_or_none((runtime.get("agent_library", {}) or {}).get("lossless_claw_path", ""))
    return [
        path
        for path in [
            configured,
            agent_path,
            Path.home() / "Axiom_research" / "external" / "lossless-claw",
        ]
        if path is not None
    ]


def resolve_lossless_claw_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "README.md").exists() and (candidate / "package.json").exists():
                return candidate
        except Exception:
            continue
    return None


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


def collect_lossless_claw_status() -> dict:
    repo = resolve_lossless_claw_repo_path()
    cfg = _lossless_claw_config()
    package_json = _read_json(repo / "package.json") if repo else {}
    return {
        "repo_path": str(repo) if repo else "",
        "database_path": str(cfg.get("database_path", "") or "").strip(),
        "node_available": bool(shutil.which("node")),
        "openclaw_available": bool(shutil.which("openclaw")),
        "package_name": str(package_json.get("name", "") or "").strip(),
        "package_version": str(package_json.get("version", "") or "").strip(),
        "plugin_manifest_present": bool(repo and (repo / "openclaw.plugin.json").exists()),
        "specs_present": bool(repo and (repo / "specs").exists()),
        "docs_present": bool(repo and (repo / "docs").exists()),
        "readme_excerpt": _read_text(repo / "README.md", limit=1100) if repo else "",
    }


def format_lossless_claw_status() -> str:
    status = collect_lossless_claw_status()
    lines = [
        "lossless-claw integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Database path: {status['database_path'] or 'default OpenClaw path'}",
        f"Node available: {'yes' if status['node_available'] else 'no'}",
        f"openclaw command available: {'yes' if status['openclaw_available'] else 'no'}",
        f"Package: {status['package_name'] or 'unknown'} {status['package_version'] or ''}".strip(),
        f"Plugin manifest present: {'yes' if status['plugin_manifest_present'] else 'no'}",
        f"Specs present: {'yes' if status['specs_present'] else 'no'}",
        f"Docs present: {'yes' if status['docs_present'] else 'no'}",
    ]
    return "\n".join(lines)


def lossless_claw_launch_instructions() -> str:
    status = collect_lossless_claw_status()
    if not status["repo_path"]:
        return (
            "lossless-claw repo path is not configured. Set lossless_claw.repo_path or place the repo at "
            "C:/Users/moyes/Axiom_research/external/lossless-claw."
        )

    if not status["openclaw_available"]:
        return (
            "lossless-claw is cloned, but OpenClaw is not installed on this machine. Once OpenClaw is available, use:\n"
            f"openclaw plugins install --link '{status['repo_path']}'"
        )

    return (
        "lossless-claw is ready as an optional OpenClaw context engine plugin. Typical commands:\n"
        f"openclaw plugins install --link '{status['repo_path']}'\n"
        "Then set plugins.slots.contextEngine to lossless-claw in your OpenClaw config."
    )
