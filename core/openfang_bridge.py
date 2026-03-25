import json
import shutil
import socket
from pathlib import Path
from urllib.parse import urlparse

from core.runtime_config import load_runtime_config, update_runtime_config


def configure_openfang(updates: dict) -> dict:
    updates = updates or {}
    merged = {"openfang": updates}
    repo_path = str(updates.get("repo_path", "") or "").strip()
    if repo_path:
        merged["skill_library"] = {"openfang_path": repo_path}
        merged["agent_library"] = {"openfang_path": repo_path}
    return update_runtime_config(merged)


def _openfang_config() -> dict:
    return load_runtime_config().get("openfang", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    runtime = load_runtime_config()
    configured = _path_or_none(_openfang_config().get("repo_path", ""))
    skill_path = _path_or_none((runtime.get("skill_library", {}) or {}).get("openfang_path", ""))
    agent_path = _path_or_none((runtime.get("agent_library", {}) or {}).get("openfang_path", ""))
    return [
        path
        for path in [
            configured,
            skill_path,
            agent_path,
            Path.home() / "Axiom_research" / "external" / "openfang",
        ]
        if path is not None
    ]


def resolve_openfang_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "Cargo.toml").exists() and (candidate / "README.md").exists():
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


def collect_openfang_status() -> dict:
    repo = resolve_openfang_repo_path()
    cfg = _openfang_config()
    dashboard_url = str(cfg.get("dashboard_url", "http://127.0.0.1:4200") or "http://127.0.0.1:4200").strip()
    return {
        "repo_path": str(repo) if repo else "",
        "dashboard_url": dashboard_url,
        "dashboard_reachable": bool(dashboard_url) and _is_tcp_reachable(dashboard_url),
        "auto_start": bool(cfg.get("auto_start", False)),
        "cargo_available": bool(shutil.which("cargo")),
        "rustc_available": bool(shutil.which("rustc")),
        "openfang_command_available": bool(shutil.which("openfang")),
        "bundled_hands": _count_files((repo / "crates" / "openfang-hands" / "bundled") if repo else None, "**/HAND.toml"),
        "bundled_skills": _count_files((repo / "crates" / "openfang-skills" / "bundled") if repo else None, "**/SKILL.md"),
        "channels_doc_present": bool(repo and (repo / "crates" / "openfang-channels").exists()),
        "desktop_present": bool(repo and (repo / "crates" / "openfang-desktop").exists()),
        "plugin_examples": bool(repo and (repo / "openfang.toml.example").exists()),
        "package_name": str(_read_json(repo / "packages" / "sdk" / "package.json").get("name", "")).strip() if repo else "",
        "readme_excerpt": _read_text(repo / "README.md", limit=1100) if repo else "",
    }


def format_openfang_status() -> str:
    status = collect_openfang_status()
    lines = [
        "OpenFang integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Dashboard URL: {status['dashboard_url']}",
        f"Dashboard reachable: {'yes' if status['dashboard_reachable'] else 'no'}",
        f"Auto-start: {'enabled' if status['auto_start'] else 'disabled'}",
        f"cargo available: {'yes' if status['cargo_available'] else 'no'}",
        f"rustc available: {'yes' if status['rustc_available'] else 'no'}",
        f"openfang command available: {'yes' if status['openfang_command_available'] else 'no'}",
        f"Bundled hands: {status['bundled_hands']}",
        f"Bundled skills: {status['bundled_skills']}",
        f"Channels crate present: {'yes' if status['channels_doc_present'] else 'no'}",
        f"Desktop app present: {'yes' if status['desktop_present'] else 'no'}",
        f"Config example present: {'yes' if status['plugin_examples'] else 'no'}",
    ]
    return "\n".join(lines)


def openfang_launch_instructions() -> str:
    status = collect_openfang_status()
    if not status["repo_path"]:
        return (
            "OpenFang repo path is not configured. Set openfang.repo_path or place the repo at "
            "C:/Users/moyes/Axiom_research/external/openfang."
        )

    if not status["cargo_available"]:
        return (
            "OpenFang is cloned but Rust tooling is missing. Install Rust, then run:\n"
            f"Set-Location '{status['repo_path']}'; cargo run --bin openfang -- start"
        )

    return (
        "OpenFang is ready as an optional agent-OS runtime. Typical commands:\n"
        f"Set-Location '{status['repo_path']}'; cargo build\n"
        f"Set-Location '{status['repo_path']}'; cargo test\n"
        f"Set-Location '{status['repo_path']}'; cargo run --bin openfang -- init\n"
        f"Set-Location '{status['repo_path']}'; cargo run --bin openfang -- start\n"
        f"Dashboard default: {status['dashboard_url']}"
    )
