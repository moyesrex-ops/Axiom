import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def configure_automaton(updates: dict) -> dict:
    return update_runtime_config({"integrations": updates or {}})


def _integration_config() -> dict:
    return load_runtime_config().get("integrations", {}) or {}


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


def _runtime_api_key_present(state_dir: Path, config: dict | None) -> bool:
    if str((config or {}).get("conwayApiKey", "") or "").strip():
        return True
    sidecar = _read_json(state_dir / "config.json") or {}
    return bool(str(sidecar.get("apiKey", "") or "").strip())


def _automaton_runtime_command(built_entry: str) -> list[str]:
    fnm = shutil.which("fnm")
    if fnm:
        return [fnm, "exec", "--using", "20", "--", "node", built_entry, "--run"]
    node = shutil.which("node") or "node"
    return [node, built_entry, "--run"]


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


def automaton_state_dir() -> Path:
    cfg = _integration_config()
    configured = str(cfg.get("automaton_state_dir", "") or "").strip()
    if configured:
        return Path(configured)
    return Path.home() / ".automaton"


def _candidate_repo_paths() -> list[Path]:
    cfg = _integration_config()
    home = Path.home()
    return [
        path
        for path in [
            _path_or_none(cfg.get("automaton_path", "")),
            BASE_DIR / "research" / "automaton",
            home / "automaton_upstream",
            home / ".conway",
        ]
        if path is not None
    ]


def resolve_automaton_repo_path() -> Path | None:
    for candidate in _candidate_repo_paths():
        try:
            if not candidate.exists():
                continue
            if (candidate / "package.json").exists() and (candidate / "src" / "index.ts").exists():
                return candidate
        except Exception:
            continue
    return None


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _read_text(path: Path, limit: int = 1800) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except Exception:
        return ""


def _truncate(text: str, limit: int = 240) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _connect_readonly(db_path: Path) -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    ).fetchone()
    return bool(row)


def _count_rows(conn: sqlite3.Connection, table: str, where_clause: str = "", params: tuple = ()) -> int:
    if not _table_exists(conn, table):
        return 0
    sql = f"SELECT COUNT(*) AS count FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    row = conn.execute(sql, params).fetchone()
    return int(row["count"]) if row else 0


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> str:
    try:
        row = conn.execute(sql, params).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    value = row[0]
    return "" if value is None else str(value)


def _collect_db_snapshot(db_path: Path) -> dict:
    snapshot = _empty_db_snapshot()

    conn = _connect_readonly(db_path)
    if conn is None:
        return snapshot

    try:
        snapshot["turn_count"] = _count_rows(conn, "turns")
        snapshot["tool_count"] = _count_rows(conn, "installed_tools", "enabled = 1")
        snapshot["skill_count"] = _count_rows(conn, "skills")
        snapshot["active_heartbeat_count"] = _count_rows(conn, "heartbeat_entries", "enabled = 1")
        snapshot["child_count"] = _count_rows(conn, "children")
        snapshot["working_memory_count"] = _count_rows(conn, "working_memory")
        snapshot["semantic_memory_count"] = _count_rows(conn, "semantic_memory")
        snapshot["procedural_memory_count"] = _count_rows(conn, "procedural_memory")
        snapshot["relationship_memory_count"] = _count_rows(conn, "relationship_memory")
        snapshot["knowledge_store_count"] = _count_rows(conn, "knowledge_store")
        snapshot["metric_snapshot_count"] = _count_rows(conn, "metric_snapshots")
        snapshot["last_turn_at"] = _scalar(conn, "SELECT MAX(timestamp) FROM turns")
        if _table_exists(conn, "identity"):
            snapshot["identity_name"] = _scalar(conn, "SELECT value FROM identity WHERE key = 'name'")
            snapshot["identity_address"] = _scalar(conn, "SELECT value FROM identity WHERE key = 'address'")
    finally:
        conn.close()

    return snapshot


def _empty_db_snapshot() -> dict:
    return {
        "turn_count": 0,
        "tool_count": 0,
        "skill_count": 0,
        "active_heartbeat_count": 0,
        "child_count": 0,
        "working_memory_count": 0,
        "semantic_memory_count": 0,
        "procedural_memory_count": 0,
        "relationship_memory_count": 0,
        "knowledge_store_count": 0,
        "metric_snapshot_count": 0,
        "last_turn_at": "",
        "identity_name": "",
        "identity_address": "",
    }


def _skills_count(skills_dir: Path) -> int:
    if not skills_dir.exists():
        return 0
    count = 0
    for child in skills_dir.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            count += 1
    return count


def collect_automaton_status() -> dict:
    repo = resolve_automaton_repo_path()
    state_dir = automaton_state_dir()
    config_path = state_dir / "automaton.json"
    db_path = state_dir / "state.db"
    soul_path = state_dir / "SOUL.md"
    heartbeat_path = state_dir / "heartbeat.yml"
    wallet_path = state_dir / "wallet.json"
    skills_dir = state_dir / "skills"
    config = _read_json(config_path) if config_path.exists() else None
    db_snapshot = _collect_db_snapshot(db_path) if db_path.exists() else _empty_db_snapshot()

    built_entry = repo / "dist" / "index.js" if repo else None
    source_entry = repo / "src" / "index.ts" if repo else None

    return {
        "repo_path": str(repo) if repo else "",
        "state_dir": str(state_dir),
        "state_exists": state_dir.exists(),
        "config_path": str(config_path) if config_path.exists() else "",
        "db_path": str(db_path) if db_path.exists() else "",
        "soul_path": str(soul_path) if soul_path.exists() else "",
        "heartbeat_path": str(heartbeat_path) if heartbeat_path.exists() else "",
        "wallet_path": str(wallet_path) if wallet_path.exists() else "",
        "skills_dir": str(skills_dir) if skills_dir.exists() else "",
        "node_modules_path": str(repo / "node_modules") if repo and (repo / "node_modules").exists() else "",
        "git_state_repo": (state_dir / ".git").exists(),
        "node_available": bool(shutil.which("node")),
        "pnpm_available": bool(shutil.which("pnpm")),
        "built_entry": str(built_entry) if built_entry and built_entry.exists() else "",
        "source_entry": str(source_entry) if source_entry and source_entry.exists() else "",
        "config_name": str((config or {}).get("name", "")).strip(),
        "config_model": str((config or {}).get("inferenceModel", "")).strip(),
        "config_version": str((config or {}).get("version", "")).strip(),
        "config_wallet": str((config or {}).get("walletAddress", "")).strip(),
        "config_sandbox": str((config or {}).get("sandboxId", "")).strip(),
        "api_key_present": _runtime_api_key_present(state_dir, config),
        "skills_disk_count": _skills_count(skills_dir),
        "soul_excerpt": _read_text(soul_path, limit=1400),
        "db_snapshot": db_snapshot,
    }


def format_automaton_status() -> str:
    status = collect_automaton_status()
    db = status["db_snapshot"]
    lines = [
        "Automaton integration",
        f"Repo path: {status['repo_path'] or 'not found'}",
        f"State dir: {status['state_dir']}",
        f"State dir exists: {'yes' if status['state_exists'] else 'no'}",
        f"Node available: {'yes' if status['node_available'] else 'no'}",
        f"pnpm available: {'yes' if status['pnpm_available'] else 'no'}",
        f"node_modules: {status['node_modules_path'] or 'missing'}",
        f"Built CLI: {status['built_entry'] or 'not built'}",
        f"Source entry: {status['source_entry'] or 'missing'}",
        f"Config file: {status['config_path'] or 'missing'}",
        f"Database file: {status['db_path'] or 'missing'}",
        f"SOUL.md: {status['soul_path'] or 'missing'}",
        f"Heartbeat file: {status['heartbeat_path'] or 'missing'}",
        f"Wallet file: {status['wallet_path'] or 'missing'}",
        f"State repo git-tracked: {'yes' if status['git_state_repo'] else 'no'}",
    ]
    if status["config_name"]:
        lines.append(f"Configured name: {status['config_name']}")
    if status["config_model"]:
        lines.append(f"Inference model: {status['config_model']}")
    if status["config_version"]:
        lines.append(f"Version: {status['config_version']}")
    if status["config_wallet"]:
        lines.append(f"Wallet address: {status['config_wallet']}")
    if status["config_sandbox"]:
        lines.append(f"Sandbox ID: {status['config_sandbox']}")
    lines.append(f"API key configured: {'yes' if status['api_key_present'] else 'no'}")

    lines.extend(
        [
            f"Turns in DB: {db['turn_count']}",
            f"Enabled tools in DB: {db['tool_count']}",
            f"Skills in DB: {db['skill_count']}",
            f"Skills on disk: {status['skills_disk_count']}",
            f"Active heartbeat entries: {db['active_heartbeat_count']}",
            f"Children tracked: {db['child_count']}",
            f"Working memory rows: {db['working_memory_count']}",
            f"Semantic memory rows: {db['semantic_memory_count']}",
            f"Procedural memory rows: {db['procedural_memory_count']}",
            f"Relationship memory rows: {db['relationship_memory_count']}",
            f"Knowledge store rows: {db['knowledge_store_count']}",
            f"Metric snapshots: {db['metric_snapshot_count']}",
        ]
    )
    if db["last_turn_at"]:
        lines.append(f"Last turn timestamp: {db['last_turn_at']}")
    if db["identity_name"]:
        lines.append(f"DB identity name: {db['identity_name']}")
    if db["identity_address"]:
        lines.append(f"DB identity address: {db['identity_address']}")
    return "\n".join(lines)


def format_automaton_memory_snapshot() -> str:
    status = collect_automaton_status()
    db = status["db_snapshot"]
    lines = [
        "Automaton memory snapshot",
        f"State dir: {status['state_dir']}",
        f"DB present: {'yes' if status['db_path'] else 'no'}",
        f"SOUL present: {'yes' if status['soul_path'] else 'no'}",
        f"Turns: {db['turn_count']}",
        f"Working memory: {db['working_memory_count']}",
        f"Semantic memory: {db['semantic_memory_count']}",
        f"Procedural memory: {db['procedural_memory_count']}",
        f"Relationship memory: {db['relationship_memory_count']}",
        f"Knowledge store: {db['knowledge_store_count']}",
        f"Metric snapshots: {db['metric_snapshot_count']}",
    ]
    if status["soul_excerpt"]:
        lines.append(f"SOUL excerpt: {_truncate(status['soul_excerpt'], 260)}")
    return "\n".join(lines)


def automaton_soul_excerpt(limit: int = 1600) -> str:
    status = collect_automaton_status()
    if not status["soul_path"]:
        return "SOUL.md was not found in the automaton state directory."
    return _read_text(Path(status["soul_path"]), limit=max(int(limit), 200))


def automaton_launch_instructions() -> str:
    repo = resolve_automaton_repo_path()
    if repo is None:
        return (
            "Automaton repo path is not configured. Set integrations.automaton_path "
            "or place the repo at C:/Users/moyes/automaton_upstream."
        )

    built_entry = repo / "dist" / "index.js"
    fnm = shutil.which("fnm")
    run_cmd = f"fnm exec --using 20 -- node dist/index.js --run" if fnm else "node dist/index.js --run"
    status_cmd = f"fnm exec --using 20 -- node dist/index.js --status" if fnm else "node dist/index.js --status"
    if built_entry.exists():
        return (
            "Launch Automaton from PowerShell with:\n"
            f"Set-Location '{repo}'; {run_cmd}\n\n"
            "Status check:\n"
            f"Set-Location '{repo}'; {status_cmd}"
        )

    return (
        "Automaton is present but not built yet. Build and launch it from PowerShell with:\n"
        f"Set-Location '{repo}'; pnpm install; pnpm build; node dist/index.js --run"
    )


def start_automaton_runtime(timeout: float = 8.0) -> dict:
    status = collect_automaton_status()
    repo_path = str(status.get("repo_path", "") or "").strip()
    if not repo_path:
        return {"started": False, "message": "Automaton repo was not found."}

    if not status.get("node_available"):
        return {"started": False, "message": "Node.js is not available on this machine."}

    built_entry = str(status.get("built_entry", "") or "").strip()
    if not built_entry:
        return {
            "started": False,
            "message": "Automaton is not built yet. Build it first with pnpm install and pnpm build.",
        }

    config_path = str(status.get("config_path", "") or "").strip()
    if not config_path:
        return {
            "started": False,
            "message": "Automaton is not configured yet. Run setup to create ~/.automaton/automaton.json.",
        }
    if not status.get("api_key_present"):
        return {
            "started": False,
            "message": "Automaton is configured without a Conway API key. Run automaton --provision or complete setup.",
        }

    repo = Path(repo_path)
    log_path = _bridge_logs_dir("automaton") / "runtime.log"
    try:
        log_handle = open(log_path, "a", encoding="utf-8")
    except Exception as exc:
        return {
            "started": False,
            "message": f"AXIOM could not open the Automaton runtime log: {exc}",
            "log_path": str(log_path),
        }
    process = None
    last_error = None
    try:
        for creationflags in _windows_creationflags():
            try:
                process = subprocess.Popen(
                    _automaton_runtime_command(built_entry),
                    cwd=str(repo),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                    env=os.environ.copy(),
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
        return {
            "started": False,
            "message": f"Failed to launch Automaton: {last_error}",
            "log_path": str(log_path),
        }

    return {
        "started": True,
        "pid": process.pid,
        "log_path": str(log_path),
        "message": "Automaton launch command was issued.",
    }
