import shutil
import sys
from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config


def configure_pentagi(updates: dict) -> dict:
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
    configured = _path_or_none(_agent_library_config().get("pentagi_path", ""))
    return [
        path
        for path in [
            configured,
            Path.home() / "Axiom_research" / "external" / "pentagi",
        ]
        if path is not None
    ]


def resolve_pentagi_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "README.md").exists():
                return candidate
        except Exception:
            continue
    return None


def _read_text(path: Path, limit: int = 1800) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def collect_pentagi_status() -> dict:
    repo = resolve_pentagi_repo_path()
    readme_text = _read_text(repo / "README.md", limit=5000) if repo else ""
    source_markers = [
        repo / "src",
        repo / "backend",
        repo / "frontend",
        repo / "docker-compose.yml",
        repo / "compose.yaml",
        repo / "api",
    ] if repo else []
    source_available = any(path.exists() for path in source_markers)
    audit_notice = "license compliance audit" in readme_text.lower()
    return {
        "repo_path": str(repo) if repo else "",
        "docker_available": bool(shutil.which("docker")),
        "readme_present": bool(repo and (repo / "README.md").exists()),
        "license_present": bool(repo and (repo / "LICENSE").exists()),
        "source_available": source_available,
        "installer_downloads_documented": "installer-latest.zip" in readme_text,
        "audit_notice_present": audit_notice,
        "feature_count": readme_text.count("- "),
        "readme_excerpt": readme_text[:1800].strip(),
    }


def format_pentagi_status() -> str:
    status = collect_pentagi_status()
    lines = [
        "PentAGI integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"README present: {'yes' if status['readme_present'] else 'no'}",
        f"LICENSE present: {'yes' if status['license_present'] else 'no'}",
        f"Docker available: {'yes' if status['docker_available'] else 'no'}",
        f"Source files present: {'yes' if status['source_available'] else 'no'}",
        f"Installer downloads documented: {'yes' if status['installer_downloads_documented'] else 'no'}",
        f"License audit notice present: {'yes' if status['audit_notice_present'] else 'no'}",
    ]
    if status["audit_notice_present"]:
        lines.append("Status note: upstream README currently says the source is temporarily unavailable during a license audit.")
    return "\n".join(lines)


def pentagi_launch_instructions() -> str:
    status = collect_pentagi_status()
    if not status["repo_path"]:
        return (
            "PentAGI repo path is not configured. Set agent_library.pentagi_path or place the repo at "
            "C:/Users/moyes/Axiom_research/external/pentagi."
        )

    if not status["source_available"]:
        return (
            "The cloned PentAGI repo currently exposes documentation only. The upstream README says the source code "
            "was temporarily removed during a license compliance audit, so AXIOM cannot truthfully run or embed that "
            "runtime yet. Use the upstream installer/download guidance when the source or packaged runtime becomes available."
        )

    return (
        "PentAGI source files are present. Follow the upstream deployment instructions from the repo README and verify "
        "Docker before attempting to start the runtime."
    )
