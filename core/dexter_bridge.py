import json
import shutil
import sys
from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config


def configure_dexter(updates: dict) -> dict:
    return update_runtime_config({"agent_library": updates or {}})


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _agent_library_config() -> dict:
    return load_runtime_config().get("agent_library", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    configured = _path_or_none(_agent_library_config().get("dexter_path", ""))
    return [
        path
        for path in [
            configured,
            Path.home() / "Axiom_research" / "external" / "dexter",
        ]
        if path is not None
    ]


def resolve_dexter_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "package.json").exists() and (candidate / "README.md").exists():
                return candidate
        except Exception:
            continue
    return None


def _read_text(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _count_files(root: Path | None, glob_pattern: str) -> int:
    if root is None or not root.exists():
        return 0
    try:
        return sum(1 for item in root.glob(glob_pattern) if item.is_file())
    except Exception:
        return 0


def collect_dexter_status() -> dict:
    repo = resolve_dexter_repo_path()
    package_json = _read_json(repo / "package.json") if repo else {}
    scripts = sorted(list((package_json.get("scripts") or {}).keys()))
    return {
        "repo_path": str(repo) if repo else "",
        "package_name": str(package_json.get("name", "") or "").strip(),
        "package_version": str(package_json.get("version", "") or "").strip(),
        "bun_available": bool(shutil.which("bun")),
        "node_available": bool(shutil.which("node")),
        "env_example_present": bool(repo and (repo / "env.example").exists()),
        "agents_doc_present": bool(repo and (repo / "AGENTS.md").exists()),
        "source_dir_present": bool(repo and (repo / "src").exists()),
        "tool_count": _count_files((repo / "src" / "tools") if repo else None, "**/*.ts"),
        "skill_count": _count_files((repo / "src" / "skills") if repo else None, "**/SKILL.md"),
        "test_count": _count_files(repo, "**/*.test.ts") if repo else 0,
        "scripts": scripts,
        "readme_excerpt": _read_text(repo / "README.md", limit=1100) if repo else "",
    }


def format_dexter_status() -> str:
    status = collect_dexter_status()
    lines = [
        "Dexter integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Package: {status['package_name'] or 'unknown'} {status['package_version'] or ''}".strip(),
        f"Bun available: {'yes' if status['bun_available'] else 'no'}",
        f"Node available: {'yes' if status['node_available'] else 'no'}",
        f"env.example present: {'yes' if status['env_example_present'] else 'no'}",
        f"AGENTS.md present: {'yes' if status['agents_doc_present'] else 'no'}",
        f"Source directory present: {'yes' if status['source_dir_present'] else 'no'}",
        f"Tool modules: {status['tool_count']}",
        f"Skill workflows: {status['skill_count']}",
        f"Test files: {status['test_count']}",
    ]
    if status["scripts"]:
        lines.append(f"Scripts: {', '.join(status['scripts'])}")
    return "\n".join(lines)


def dexter_launch_instructions() -> str:
    status = collect_dexter_status()
    if not status["repo_path"]:
        return (
            "Dexter repo path is not configured. Set agent_library.dexter_path or place the repo at "
            "C:/Users/moyes/Axiom_research/external/dexter."
        )

    if not status["bun_available"]:
        return (
            "Dexter is cloned but Bun is not installed on this machine. Install Bun first, then run:\n"
            f"Set-Location '{status['repo_path']}'; bun install; bun run start"
        )

    return (
        "Dexter is ready as an optional sidecar financial research runtime. Typical commands:\n"
        f"Set-Location '{status['repo_path']}'; bun install\n"
        f"Set-Location '{status['repo_path']}'; bun run typecheck\n"
        f"Set-Location '{status['repo_path']}'; bun test\n"
        f"Set-Location '{status['repo_path']}'; bun run start"
    )
