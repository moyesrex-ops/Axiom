import csv
import sys
import shutil
import subprocess
from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config


def configure_autoresearch(updates: dict) -> dict:
    return update_runtime_config({"research_repos": updates or {}})


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _research_repo_config() -> dict:
    return load_runtime_config().get("research_repos", {}) or {}


def _path_or_none(value: str | Path | None) -> Path | None:
    value = str(value or "").strip()
    return Path(value) if value else None


def _candidate_repo_paths() -> list[Path]:
    configured = _path_or_none(_research_repo_config().get("autoresearch_path", ""))
    return [
        path
        for path in [
            configured,
            Path.home() / "Axiom_research" / "external" / "autoresearch",
        ]
        if path is not None
    ]


def resolve_autoresearch_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if candidate.exists() and (candidate / "program.md").exists() and (candidate / "train.py").exists():
                return candidate
        except Exception:
            continue
    return None


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


def _append_log(log_path: Path, text: str) -> None:
    with log_path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _run_text(command: list[str], cwd: Path | None = None, timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return ""
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return ""
    return output.splitlines()[0][:220]


def _run_logged(command: list[str], cwd: Path, log_path: Path, timeout: int) -> dict:
    _append_log(log_path, f"$ {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        message = f"Command failed to start: {exc}"
        _append_log(log_path, message)
        return {"ok": False, "message": message, "output": ""}

    output = "\n".join(
        part.strip()
        for part in [result.stdout or "", result.stderr or ""]
        if part.strip()
    ).strip()
    if output:
        _append_log(log_path, output)

    message = output.splitlines()[-1][:260] if output else "Command finished with no output."
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "message": message,
        "output": output[:4000],
    }


def _gpu_summary() -> str:
    if not shutil.which("nvidia-smi"):
        return ""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return ""
    return (result.stdout or "").strip().splitlines()[0][:220] if result.stdout else ""


def _cache_dir() -> Path:
    return Path.home() / ".cache" / "autoresearch"


def _results_rows(results_path: Path, limit: int = 5) -> list[dict]:
    if not results_path.exists():
        return []
    try:
        with results_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except Exception:
        return []
    rows = [row for row in rows if isinstance(row, dict)]
    rows.reverse()
    return rows[: max(int(limit), 1)]


def _count_data_shards(data_dir: Path) -> int:
    if not data_dir.exists():
        return 0
    return sum(1 for item in data_dir.glob("*.parquet") if item.is_file())


def collect_autoresearch_status(limit: int = 5) -> dict:
    repo = resolve_autoresearch_repo_path()
    cache_dir = _cache_dir()
    data_dir = cache_dir / "data"
    tokenizer_dir = cache_dir / "tokenizer"
    results_path = (repo / "results.tsv") if repo else Path("")
    recent_results = _results_rows(results_path, limit=limit) if repo else []

    return {
        "repo_path": str(repo) if repo else "",
        "program_path": str(repo / "program.md") if repo else "",
        "readme_path": str(repo / "README.md") if repo and (repo / "README.md").exists() else "",
        "train_path": str(repo / "train.py") if repo else "",
        "prepare_path": str(repo / "prepare.py") if repo else "",
        "pyproject_path": str(repo / "pyproject.toml") if repo else "",
        "results_path": str(results_path) if repo and results_path.exists() else "",
        "results_count": len(_results_rows(results_path, limit=100000)) if repo and results_path.exists() else 0,
        "recent_results": recent_results,
        "uv_available": bool(shutil.which("uv")),
        "python_version": _run_text(["python", "--version"]),
        "uv_version": _run_text(["uv", "--version"]) if shutil.which("uv") else "",
        "gpu_available": bool(shutil.which("nvidia-smi")),
        "gpu_summary": _gpu_summary(),
        "git_branch": _run_text(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo) if repo else "",
        "git_commit": _run_text(["git", "rev-parse", "--short", "HEAD"], cwd=repo) if repo else "",
        "cache_dir": str(cache_dir),
        "cache_present": cache_dir.exists(),
        "data_dir": str(data_dir),
        "data_shards": _count_data_shards(data_dir),
        "tokenizer_dir": str(tokenizer_dir),
        "tokenizer_ready": (tokenizer_dir / "tokenizer.pkl").exists() and (tokenizer_dir / "token_bytes.pt").exists(),
    }


def format_autoresearch_status(limit: int = 5) -> str:
    status = collect_autoresearch_status(limit=limit)
    lines = [
        "Autoresearch integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"uv available: {'yes' if status['uv_available'] else 'no'}",
        f"uv version: {status['uv_version'] or 'unknown'}",
        f"Python: {status['python_version'] or 'unknown'}",
        f"NVIDIA GPU available: {'yes' if status['gpu_available'] else 'no'}",
        f"GPU summary: {status['gpu_summary'] or 'not detected'}",
        f"Git branch: {status['git_branch'] or 'unknown'}",
        f"Git commit: {status['git_commit'] or 'unknown'}",
        f"Cache dir: {status['cache_dir']}",
        f"Cache present: {'yes' if status['cache_present'] else 'no'}",
        f"Data shards: {status['data_shards']}",
        f"Tokenizer ready: {'yes' if status['tokenizer_ready'] else 'no'}",
        f"results.tsv present: {'yes' if status['results_path'] else 'no'}",
        f"Logged experiments: {status['results_count']}",
    ]
    if status["recent_results"]:
        lines.append("Recent experiment rows:")
        for row in status["recent_results"]:
            lines.append(
                f"- {row.get('commit', 'unknown')} | val_bpb={row.get('val_bpb', 'n/a')} "
                f"| mem_gb={row.get('memory_gb', 'n/a')} | {row.get('status', 'n/a')} "
                f"| {str(row.get('description', '')).strip()[:90]}"
            )
    return "\n".join(lines)


def autoresearch_program_excerpt(limit: int = 1800) -> str:
    repo = resolve_autoresearch_repo_path()
    if repo is None:
        return "Autoresearch repo was not found."
    try:
        return (repo / "program.md").read_text(encoding="utf-8", errors="replace")[: max(int(limit), 300)].strip()
    except Exception as exc:
        return f"Could not read program.md: {exc}"


def format_autoresearch_results(limit: int = 8) -> str:
    status = collect_autoresearch_status(limit=limit)
    if not status["results_path"]:
        return "results.tsv has not been created yet in the autoresearch repo."
    rows = status["recent_results"]
    if not rows:
        return "results.tsv exists but no experiment rows were parsed."
    lines = ["Autoresearch results"]
    for row in rows:
        lines.append(
            f"- commit={row.get('commit', 'unknown')} val_bpb={row.get('val_bpb', 'n/a')} "
            f"memory_gb={row.get('memory_gb', 'n/a')} status={row.get('status', 'n/a')} "
            f"description={str(row.get('description', '')).strip()[:120]}"
        )
    return "\n".join(lines)


def autoresearch_launch_instructions() -> str:
    status = collect_autoresearch_status(limit=3)
    repo_path = status["repo_path"]
    if not repo_path:
        return (
            "Autoresearch repo path is not configured. Set research_repos.autoresearch_path "
            "or place the repo at C:/Users/moyes/Axiom_research/external/autoresearch."
        )

    if not status["uv_available"]:
        return (
            "Autoresearch is cloned, but uv is not available. Install uv first, then run:\n"
            f"Set-Location '{repo_path}'; uv sync; uv run prepare.py; uv run train.py"
        )

    if status["data_shards"] < 2 or not status["tokenizer_ready"]:
        return (
            "Autoresearch needs data and tokenizer prep before training. Run:\n"
            f"Set-Location '{repo_path}'; uv sync; uv run prepare.py"
        )

    return (
        "Autoresearch is ready for a baseline or agent-driven experiment loop. Typical commands:\n"
        f"Set-Location '{repo_path}'; uv run train.py\n"
        f"Set-Location '{repo_path}'; Get-Content program.md\n"
        f"Set-Location '{repo_path}'; Get-Content results.tsv"
    )


def prepare_autoresearch_repo(timeout: int = 1800) -> dict:
    status = collect_autoresearch_status(limit=3)
    repo_path = Path(status["repo_path"]) if status["repo_path"] else None
    if repo_path is None:
        return {"prepared": False, "message": "Autoresearch repo was not found."}
    if not status["uv_available"]:
        return {"prepared": False, "message": "uv is not installed on this machine."}
    if status["data_shards"] >= 2 and status["tokenizer_ready"]:
        return {
            "prepared": True,
            "already_prepared": True,
            "message": "Autoresearch data shards and tokenizer are already prepared.",
        }

    log_path = _bridge_logs_dir("autoresearch") / "prepare.log"
    sync_result = _run_logged(["uv", "sync"], cwd=repo_path, log_path=log_path, timeout=min(timeout, 1200))
    if not sync_result["ok"]:
        return {
            "prepared": False,
            "log_path": str(log_path),
            "message": f"uv sync failed: {sync_result['message']}",
            "output_excerpt": sync_result["output"][:1200],
        }

    prepare_result = _run_logged(["uv", "run", "prepare.py"], cwd=repo_path, log_path=log_path, timeout=timeout)
    post = collect_autoresearch_status(limit=3)
    prepared = post["data_shards"] >= 2 and post["tokenizer_ready"]
    return {
        "prepared": prepared and prepare_result["ok"],
        "log_path": str(log_path),
        "message": (
            "Autoresearch prepare completed successfully."
            if prepared and prepare_result["ok"]
            else f"Autoresearch prepare finished without reaching ready state: {prepare_result['message']}"
        ),
        "data_shards": post["data_shards"],
        "tokenizer_ready": post["tokenizer_ready"],
        "output_excerpt": prepare_result["output"][:1200],
    }


def train_autoresearch_repo(timeout: int = 1800) -> dict:
    status = collect_autoresearch_status(limit=3)
    repo_path = Path(status["repo_path"]) if status["repo_path"] else None
    if repo_path is None:
        return {"trained": False, "message": "Autoresearch repo was not found."}
    if not status["uv_available"]:
        return {"trained": False, "message": "uv is not installed on this machine."}
    if status["data_shards"] < 2 or not status["tokenizer_ready"]:
        return {
            "trained": False,
            "message": "Autoresearch is not prepared yet. Run prepare first so data shards and tokenizer exist.",
        }

    log_path = _bridge_logs_dir("autoresearch") / "train.log"
    train_result = _run_logged(["uv", "run", "train.py"], cwd=repo_path, log_path=log_path, timeout=timeout)
    post = collect_autoresearch_status(limit=3)
    return {
        "trained": train_result["ok"],
        "log_path": str(log_path),
        "message": (
            "Autoresearch train completed."
            if train_result["ok"]
            else f"Autoresearch train failed: {train_result['message']}"
        ),
        "results_count": post["results_count"],
        "output_excerpt": train_result["output"][:1200],
    }
