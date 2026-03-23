import json
import sqlite3
import sys
import threading
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
DB_PATH = BASE_DIR / "memory" / "axiom_state.db"
_LOCK = threading.Lock()
_INITIALIZED = False


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_runtime_store() -> None:
    global _INITIALIZED
    with _LOCK:
        if _INITIALIZED:
            return

        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    kind TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    tool TEXT NOT NULL,
                    description TEXT NOT NULL,
                    error TEXT NOT NULL,
                    fix_suggestion TEXT NOT NULL DEFAULT '',
                    resolved INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS capabilities (
                    name TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS task_runs (
                    task_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_text TEXT NOT NULL DEFAULT '',
                    error_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.commit()

        _INITIALIZED = True


def log_event(kind: str, topic: str, content: str, metadata: dict | None = None) -> None:
    init_runtime_store()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO events (kind, topic, content, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                kind or "general",
                topic or "untitled",
                content or "",
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        conn.commit()


def log_failure(
    tool: str,
    description: str,
    error: str,
    fix_suggestion: str = "",
    resolved: bool = False,
) -> int:
    init_runtime_store()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO failures (tool, description, error, fix_suggestion, resolved)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tool or "unknown", description or "", error or "", fix_suggestion or "", int(resolved)),
        )
        conn.commit()
        return int(cursor.lastrowid)


def mark_failure_resolved(failure_id: int) -> None:
    if not failure_id:
        return
    init_runtime_store()
    with _LOCK, _connect() as conn:
        conn.execute("UPDATE failures SET resolved = 1 WHERE id = ?", (int(failure_id),))
        conn.commit()


def log_capability(name: str, status: str, details: str = "") -> None:
    init_runtime_store()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO capabilities (name, status, details, last_seen_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET
                status = excluded.status,
                details = excluded.details,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            (name, status, details),
        )
        conn.commit()


def recent_events(limit: int = 10) -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, kind, topic, content, metadata_json
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_failures(limit: int = 10) -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, tool, description, error, fix_suggestion, resolved
            FROM failures
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def capability_rows() -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT name, status, details, last_seen_at
            FROM capabilities
            ORDER BY name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_task_run(
    task_id: str,
    goal: str,
    status: str,
    result_text: str = "",
    error_text: str = "",
    metadata: dict | None = None,
) -> None:
    init_runtime_store()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO task_runs (
                task_id, goal, status, result_text, error_text, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP,
                goal = excluded.goal,
                status = excluded.status,
                result_text = excluded.result_text,
                error_text = excluded.error_text,
                metadata_json = excluded.metadata_json
            """,
            (
                str(task_id or "").strip(),
                str(goal or "").strip(),
                str(status or "").strip(),
                str(result_text or ""),
                str(error_text or ""),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        conn.commit()


def recent_task_runs(limit: int = 10) -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                task_id,
                created_at,
                updated_at,
                goal,
                status,
                result_text,
                error_text,
                metadata_json
            FROM task_runs
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]
