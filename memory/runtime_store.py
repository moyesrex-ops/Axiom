import json
import re
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
_STOPWORDS = {
    "about", "after", "again", "also", "because", "been", "being", "between",
    "could", "does", "doing", "from", "have", "into", "just", "like", "more",
    "most", "need", "only", "over", "some", "than", "that", "their", "them",
    "then", "there", "these", "they", "this", "those", "through", "very",
    "want", "were", "what", "when", "where", "which", "while", "with", "would",
    "your", "you're", "axiom",
}


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

                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL DEFAULT '',
                    keywords_json TEXT NOT NULL DEFAULT '[]'
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


def _tokenize(text: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[a-zA-Z0-9_'-]+", str(text or "").lower()):
        token = token.strip("'")
        if len(token) < 4 or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def log_conversation_turn(user_text: str, assistant_text: str = "") -> None:
    init_runtime_store()
    user_text = str(user_text or "").strip()
    assistant_text = str(assistant_text or "").strip()
    if not user_text:
        return

    keywords = sorted(set(_tokenize(user_text) + _tokenize(assistant_text)))[:30]
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_turns (user_text, assistant_text, keywords_json)
            VALUES (?, ?, ?)
            """,
            (user_text[:4000], assistant_text[:4000], json.dumps(keywords, ensure_ascii=False)),
        )
        conn.commit()


def recent_events(limit: int = 10, kind: str | None = None) -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        if kind:
            rows = conn.execute(
                """
                SELECT id, created_at, kind, topic, content, metadata_json
                FROM events
                WHERE kind = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(kind), int(limit)),
            ).fetchall()
        else:
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


def recent_conversation_turns(limit: int = 8) -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, user_text, assistant_text, keywords_json
            FROM conversation_turns
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def search_conversation_turns(query: str, limit: int = 5, window: int = 250) -> list[dict]:
    init_runtime_store()
    terms = set(_tokenize(query))
    if not terms:
        return recent_conversation_turns(limit=limit)

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, user_text, assistant_text, keywords_json
            FROM conversation_turns
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(window),),
        ).fetchall()

    scored: list[tuple[int, int, dict]] = []
    for row in rows:
        data = dict(row)
        try:
            row_terms = set(json.loads(data.get("keywords_json") or "[]"))
        except Exception:
            row_terms = set()
        overlap = len(terms & row_terms)
        if overlap <= 0:
            continue
        scored.append((overlap, int(data["id"]), data))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[: int(limit)]]
