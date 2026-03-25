from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config


def configure_symphony(updates: dict) -> dict:
    updates = updates or {}
    merged = {"symphony": updates}
    repo_path = str(updates.get("repo_path", "") or "").strip()
    if repo_path:
        merged["agent_library"] = {"symphony_path": repo_path}
    return update_runtime_config(merged)


def _symphony_config() -> dict:
    return load_runtime_config().get("symphony", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    runtime = load_runtime_config()
    configured = _path_or_none(_symphony_config().get("repo_path", ""))
    agent_path = _path_or_none((runtime.get("agent_library", {}) or {}).get("symphony_path", ""))
    return [
        path
        for path in [
            configured,
            agent_path,
            Path.home() / "Axiom_research" / "external" / "symphony",
        ]
        if path is not None
    ]


def resolve_symphony_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "README.md").exists() and (candidate / "SPEC.md").exists():
                return candidate
        except Exception:
            continue
    return None


def _read_text(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def collect_symphony_status() -> dict:
    repo = resolve_symphony_repo_path()
    cfg = _symphony_config()
    workflow_path = str(cfg.get("workflow_path", "WORKFLOW.md") or "WORKFLOW.md").strip()
    return {
        "repo_path": str(repo) if repo else "",
        "workflow_path": workflow_path,
        "spec_present": bool(repo and (repo / "SPEC.md").exists()),
        "elixir_reference_present": bool(repo and (repo / "elixir").exists()),
        "codex_assets_present": bool(repo and (repo / ".codex").exists()),
        "workflow_contract_note": "Repository-owned WORKFLOW.md policy is the core runtime contract.",
        "readme_excerpt": _read_text(repo / "README.md", limit=1100) if repo else "",
    }


def format_symphony_status() -> str:
    status = collect_symphony_status()
    lines = [
        "Symphony integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"Workflow contract path: {status['workflow_path']}",
        f"SPEC.md present: {'yes' if status['spec_present'] else 'no'}",
        f"Elixir reference present: {'yes' if status['elixir_reference_present'] else 'no'}",
        f"Codex assets present: {'yes' if status['codex_assets_present'] else 'no'}",
        status["workflow_contract_note"],
    ]
    return "\n".join(lines)


def symphony_launch_instructions() -> str:
    status = collect_symphony_status()
    if not status["repo_path"]:
        return (
            "Symphony repo path is not configured. Set symphony.repo_path or place the repo at "
            "C:/Users/moyes/Axiom_research/external/symphony."
        )

    return (
        "Symphony is integrated as an orchestration reference. Start with these assets:\n"
        f"- Spec: {Path(status['repo_path']) / 'SPEC.md'}\n"
        f"- Workflow contract: create or adapt {status['workflow_path']} in the target repo\n"
        f"- Reference implementation notes: {Path(status['repo_path']) / 'elixir' / 'README.md'}"
    )
