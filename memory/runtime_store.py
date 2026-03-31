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
_GRAPH_COMPONENT_NAMES = {
    "axiom": ("AXIOM", "assistant"),
    "telegram": ("Telegram", "channel"),
    "mirofish": ("MiroFish", "integration"),
    "automaton": ("Automaton", "integration"),
    "tradingagents": ("TradingAgents", "integration"),
    "lightpanda": ("Lightpanda", "integration"),
    "dexter": ("Dexter", "integration"),
    "pentagi": ("PentAGI", "integration"),
    "codex": ("Codex CLI", "builder"),
    "playwright": ("Playwright", "browser"),
    "openrgb": ("OpenRGB", "hardware"),
    "mt5": ("MetaTrader5", "trading"),
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except Exception:
        return set()
    return {str(row["name"]) if isinstance(row, sqlite3.Row) else str(row[1]) for row in rows}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_def: str) -> None:
    column_name = str(column_def or "").split()[0].strip()
    if not column_name:
        return
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")


def _safe_json_loads(raw: str, default):
    try:
        payload = json.loads(raw or "")
        return payload if isinstance(payload, type(default)) else default
    except Exception:
        return default


def _tokenize(text: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[a-zA-Z0-9_'-]+", str(text or "").lower()):
        token = token.strip("'")
        if len(token) < 4 or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _fts_match_query(query: str) -> str:
    terms = []
    seen = set()
    for token in _tokenize(query):
        if token in seen:
            continue
        seen.add(token)
        terms.append(f'"{token}"')
    return " OR ".join(terms[:10])


def _create_fts_tables(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS conversation_turns_fts
            USING fts5(user_text, assistant_text)
            """
        )
        conn.execute(
            """
            INSERT INTO conversation_turns_fts(rowid, user_text, assistant_text)
            SELECT c.id, c.user_text, c.assistant_text
            FROM conversation_turns c
            WHERE NOT EXISTS (
                SELECT 1 FROM conversation_turns_fts f WHERE f.rowid = c.id
            )
            """
        )
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_items_fts
            USING fts5(title, content)
            """
        )
        conn.execute(
            """
            INSERT INTO knowledge_items_fts(rowid, title, content)
            SELECT k.id, k.title, k.content
            FROM knowledge_items k
            WHERE NOT EXISTS (
                SELECT 1 FROM knowledge_items_fts f WHERE f.rowid = k.id
            )
            """
        )
    except sqlite3.OperationalError:
        pass


def _normalize_entity_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def _clean_fact_value(value: str, limit: int = 72) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,.;:!?\"'")
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip(" ,.;:!?") + "..."
    return cleaned


def _title_case_value(value: str) -> str:
    words = [part for part in re.split(r"\s+", str(value or "").strip()) if part]
    if not words:
        return ""
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _extract_graph_facts(primary_text: str, secondary_text: str = "", source_kind: str = "conversation") -> list[dict]:
    facts: list[dict] = []
    user_text = str(primary_text or "").strip()
    secondary = str(secondary_text or "").strip()
    combined = f"{user_text}\n{secondary}".strip()
    lower_combined = combined.lower()

    user_patterns = (
        (r"\bmy name is ([a-z][a-z0-9' -]{1,40})", "name_is", "person"),
        (r"\bcall me ([a-z][a-z0-9' -]{1,40})", "prefers_address", "person"),
        (r"\baddress me as ([a-z][a-z0-9' -]{1,40})", "prefers_address", "person"),
        (r"\bi live in ([a-z][a-z0-9' -]{1,48})", "located_in", "place"),
        (r"\bi work (?:at|for) ([a-z][a-z0-9'&., -]{1,56})", "works_at", "organization"),
        (r"\bi prefer to be addressed as ([a-z][a-z0-9' -]{1,40})", "prefers_address", "person"),
        (r"\bi prefer ([a-z][a-z0-9'&., -]{1,56})", "prefers", "preference"),
        (r"\bi like ([a-z][a-z0-9'&., -]{1,56})", "likes", "interest"),
        (r"\bi love ([a-z][a-z0-9'&., -]{1,56})", "likes", "interest"),
    )
    for pattern, relation, target_kind in user_patterns:
        match = re.search(pattern, user_text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_value = _clean_fact_value(match.group(1))
        if not raw_value:
            continue
        target = _title_case_value(raw_value)
        facts.append(
            {
                "source_name": "User",
                "source_kind": "person",
                "relation": relation,
                "target_name": target,
                "target_kind": target_kind,
                "evidence": user_text[:220],
                "metadata": {"source_kind": source_kind},
            }
        )

    mentioned_components = []
    for needle, (display_name, target_kind) in _GRAPH_COMPONENT_NAMES.items():
        if re.search(rf"\b{re.escape(needle)}\b", lower_combined, flags=re.IGNORECASE):
            mentioned_components.append((display_name, target_kind))
    for display_name, target_kind in mentioned_components[:8]:
        facts.append(
            {
                "source_name": "AXIOM",
                "source_kind": "assistant",
                "relation": "tracks",
                "target_name": display_name,
                "target_kind": target_kind,
                "evidence": combined[:220],
                "metadata": {"source_kind": source_kind},
            }
        )

    return facts


def _index_graph_from_text(primary_text: str, secondary_text: str = "", source_kind: str = "conversation") -> None:
    try:
        facts = _extract_graph_facts(primary_text, secondary_text, source_kind=source_kind)
        for fact in facts:
            upsert_graph_relation(
                source_name=fact["source_name"],
                relation=fact["relation"],
                target_name=fact["target_name"],
                source_kind=fact["source_kind"],
                target_kind=fact["target_kind"],
                evidence=fact["evidence"],
                metadata=fact["metadata"],
            )
    except Exception:
        pass


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

                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    phase TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS task_steps (
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    step_index INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    tool TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    result_text TEXT NOT NULL DEFAULT '',
                    error_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(task_id, revision, step_index)
                );

                CREATE TABLE IF NOT EXISTS tool_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    tool TEXT NOT NULL,
                    args_json TEXT NOT NULL DEFAULT '{}',
                    result_text TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL DEFAULT 1,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    channel TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
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

                CREATE TABLE IF NOT EXISTS channel_states (
                    channel TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    active_task_id TEXT NOT NULL DEFAULT '',
                    last_task_id TEXT NOT NULL DEFAULT '',
                    last_goal TEXT NOT NULL DEFAULT '',
                    last_result TEXT NOT NULL DEFAULT '',
                    last_user_text TEXT NOT NULL DEFAULT '',
                    last_assistant_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(channel, scope)
                );

                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(kind, title)
                );

                CREATE TABLE IF NOT EXISTS graph_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL DEFAULT 'entity',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS graph_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source_entity_id INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    target_entity_id INTEGER NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(source_entity_id, relation, target_entity_id),
                    FOREIGN KEY(source_entity_id) REFERENCES graph_entities(id),
                    FOREIGN KEY(target_entity_id) REFERENCES graph_entities(id)
                );
                """
            )
            _ensure_column(conn, "conversation_turns", "channel TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "conversation_turns", "channel_scope TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "conversation_turns", "metadata_json TEXT NOT NULL DEFAULT '{}'")
            _create_fts_tables(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_channel
                ON conversation_turns(channel, channel_scope, id DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_traces_tool_created
                ON tool_traces(tool, created_at DESC, id DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_events_task_created
                ON task_events(task_id, id DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_steps_task_revision
                ON task_steps(task_id, revision DESC, step_index ASC)
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


def log_conversation_turn(
    user_text: str,
    assistant_text: str = "",
    channel: str = "",
    channel_scope: str = "",
    metadata: dict | None = None,
) -> None:
    init_runtime_store()
    user_text = str(user_text or "").strip()
    assistant_text = str(assistant_text or "").strip()
    channel = str(channel or "").strip().lower()
    channel_scope = str(channel_scope or "").strip()
    if not user_text:
        return

    keywords = sorted(set(_tokenize(user_text) + _tokenize(assistant_text)))[:30]
    metadata_payload = json.dumps(metadata or {}, ensure_ascii=False)
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO conversation_turns (
                user_text,
                assistant_text,
                keywords_json,
                channel,
                channel_scope,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_text[:4000],
                assistant_text[:4000],
                json.dumps(keywords, ensure_ascii=False),
                channel,
                channel_scope[:255],
                metadata_payload,
            ),
        )
        turn_id = int(cursor.lastrowid)
        try:
            conn.execute(
                """
                INSERT INTO conversation_turns_fts(rowid, user_text, assistant_text)
                VALUES (?, ?, ?)
                """,
                (turn_id, user_text[:4000], assistant_text[:4000]),
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
    if channel:
        upsert_channel_state(
            channel=channel,
            scope=channel_scope,
            last_user_text=user_text[:4000],
            last_assistant_text=assistant_text[:4000],
            metadata={"last_turn_source": "conversation", **(metadata or {})},
        )
        if channel in {"voice", "telegram"}:
            upsert_channel_state(
                channel="operator",
                scope="shared",
                last_user_text=user_text[:4000],
                last_assistant_text=assistant_text[:4000],
                metadata={
                    "last_turn_source": "conversation",
                    "last_channel": channel,
                    "last_scope": channel_scope,
                    **(metadata or {}),
                },
            )
    _index_graph_from_text(user_text, assistant_text, source_kind="conversation")


def upsert_knowledge_item(
    kind: str,
    title: str,
    content: str,
    source: str = "",
    metadata: dict | None = None,
) -> int:
    init_runtime_store()
    kind = str(kind or "general").strip() or "general"
    title = str(title or "untitled").strip() or "untitled"
    content = str(content or "").strip()

    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT id FROM knowledge_items WHERE kind = ? AND title = ?",
            (kind, title),
        ).fetchone()

        if row:
            item_id = int(row["id"])
            conn.execute(
                """
                UPDATE knowledge_items
                SET updated_at = CURRENT_TIMESTAMP,
                    content = ?,
                    source = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (content, str(source or ""), json.dumps(metadata or {}, ensure_ascii=False), item_id),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_items (kind, title, content, source, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    title,
                    content,
                    str(source or ""),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            item_id = int(cursor.lastrowid)

        try:
            conn.execute("DELETE FROM knowledge_items_fts WHERE rowid = ?", (item_id,))
            conn.execute(
                """
                INSERT INTO knowledge_items_fts(rowid, title, content)
                VALUES (?, ?, ?)
                """,
                (item_id, title, content),
            )
        except sqlite3.OperationalError:
            pass

        conn.commit()
    _index_graph_from_text(title, content, source_kind=f"knowledge:{kind}")
    return item_id


def upsert_graph_entity(name: str, kind: str = "entity", metadata: dict | None = None) -> int:
    init_runtime_store()
    display_name = re.sub(r"\s+", " ", str(name or "").strip())
    normalized_name = _normalize_entity_name(display_name)
    if not normalized_name:
        return 0

    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT id FROM graph_entities WHERE normalized_name = ?",
            (normalized_name,),
        ).fetchone()
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        if row:
            entity_id = int(row["id"])
            conn.execute(
                """
                UPDATE graph_entities
                SET updated_at = CURRENT_TIMESTAMP,
                    name = ?,
                    kind = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (display_name, str(kind or "entity"), payload, entity_id),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO graph_entities (name, normalized_name, kind, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (display_name, normalized_name, str(kind or "entity"), payload),
            )
            entity_id = int(cursor.lastrowid)
        conn.commit()
        return entity_id


def upsert_graph_relation(
    source_name: str,
    relation: str,
    target_name: str,
    source_kind: str = "entity",
    target_kind: str = "entity",
    evidence: str = "",
    metadata: dict | None = None,
) -> int:
    init_runtime_store()
    normalized_relation = _normalize_entity_name(relation).replace(" ", "_")
    if not normalized_relation:
        return 0

    source_id = upsert_graph_entity(source_name, kind=source_kind)
    target_id = upsert_graph_entity(target_name, kind=target_kind)
    if not source_id or not target_id:
        return 0

    with _LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM graph_relations
            WHERE source_entity_id = ? AND relation = ? AND target_entity_id = ?
            """,
            (int(source_id), normalized_relation, int(target_id)),
        ).fetchone()
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        if row:
            relation_id = int(row["id"])
            conn.execute(
                """
                UPDATE graph_relations
                SET updated_at = CURRENT_TIMESTAMP,
                    evidence = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (str(evidence or "")[:600], payload, relation_id),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO graph_relations (
                    source_entity_id, relation, target_entity_id, evidence, metadata_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(source_id), normalized_relation, int(target_id), str(evidence or "")[:600], payload),
            )
            relation_id = int(cursor.lastrowid)
        conn.commit()
        return relation_id


def search_knowledge_items(
    query: str,
    limit: int = 5,
    kinds: list[str] | None = None,
) -> list[dict]:
    init_runtime_store()
    kinds = [str(kind).strip() for kind in (kinds or []) if str(kind).strip()]
    match_query = _fts_match_query(query)

    with _connect() as conn:
        if match_query:
            try:
                where_clause = ""
                params: list = [match_query]
                if kinds:
                    placeholders = ",".join("?" for _ in kinds)
                    where_clause = f" AND k.kind IN ({placeholders})"
                    params.extend(kinds)
                params.append(int(limit))
                rows = conn.execute(
                    f"""
                    SELECT
                        k.id,
                        k.created_at,
                        k.updated_at,
                        k.kind,
                        k.title,
                        k.content,
                        k.source,
                        k.metadata_json,
                        bm25(knowledge_items_fts) AS score
                    FROM knowledge_items_fts
                    JOIN knowledge_items k ON knowledge_items_fts.rowid = k.id
                    WHERE knowledge_items_fts MATCH ?{where_clause}
                    ORDER BY score ASC, k.updated_at DESC
                    LIMIT ?
                    """,
                    tuple(params),
                ).fetchall()
                return [dict(row) for row in rows]
            except sqlite3.OperationalError:
                pass

        rows = conn.execute(
            """
            SELECT id, created_at, updated_at, kind, title, content, source, metadata_json
            FROM knowledge_items
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (max(int(limit) * 6, 20),),
        ).fetchall()

    query_terms = set(_tokenize(query))
    scored: list[tuple[int, int, dict]] = []
    for row in rows:
        data = dict(row)
        if kinds and data.get("kind") not in kinds:
            continue
        haystack = f"{data.get('title', '')}\n{data.get('content', '')}".lower()
        score = sum(1 for token in query_terms if token in haystack)
        if score <= 0:
            continue
        scored.append((score, int(data["id"]), data))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[: int(limit)]]


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


def recent_graph_relations(limit: int = 8) -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                r.id,
                r.created_at,
                r.updated_at,
                r.relation,
                r.evidence,
                r.metadata_json,
                s.name AS source_name,
                s.kind AS source_kind,
                t.name AS target_name,
                t.kind AS target_kind
            FROM graph_relations r
            JOIN graph_entities s ON s.id = r.source_entity_id
            JOIN graph_entities t ON t.id = r.target_entity_id
            ORDER BY r.updated_at DESC, r.id DESC
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


def append_task_event(
    task_id: str,
    topic: str,
    content: str = "",
    *,
    phase: str = "",
    metadata: dict | None = None,
) -> int:
    init_runtime_store()
    task_id = str(task_id or "").strip()
    if not task_id:
        return 0
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO task_events (task_id, phase, topic, content, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                task_id,
                str(phase or "").strip(),
                str(topic or "").strip() or "event",
                str(content or "")[:4000],
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def upsert_task_step(
    task_id: str,
    step_index: int,
    *,
    revision: int = 1,
    tool: str = "",
    description: str = "",
    status: str = "",
    parameters: dict | None = None,
    result_text: str = "",
    error_text: str = "",
    metadata: dict | None = None,
) -> None:
    init_runtime_store()
    task_id = str(task_id or "").strip()
    if not task_id:
        return
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO task_steps (
                task_id,
                revision,
                step_index,
                tool,
                description,
                status,
                parameters_json,
                result_text,
                error_text,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id, revision, step_index) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP,
                tool = excluded.tool,
                description = excluded.description,
                status = excluded.status,
                parameters_json = excluded.parameters_json,
                result_text = excluded.result_text,
                error_text = excluded.error_text,
                metadata_json = excluded.metadata_json
            """,
            (
                task_id,
                max(int(revision or 1), 1),
                int(step_index),
                str(tool or "").strip(),
                str(description or "")[:1000],
                str(status or "").strip(),
                json.dumps(parameters or {}, ensure_ascii=False),
                str(result_text or "")[:12000],
                str(error_text or "")[:4000],
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        conn.commit()


def upsert_channel_state(
    channel: str,
    scope: str = "",
    *,
    active_task_id: str | None = None,
    last_task_id: str | None = None,
    last_goal: str | None = None,
    last_result: str | None = None,
    last_user_text: str | None = None,
    last_assistant_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    init_runtime_store()
    channel = str(channel or "").strip().lower()
    scope = str(scope or "").strip()
    if not channel:
        return

    defaults = {
        "active_task_id": "",
        "last_task_id": "",
        "last_goal": "",
        "last_result": "",
        "last_user_text": "",
        "last_assistant_text": "",
        "metadata_json": "{}",
    }

    with _LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT
                active_task_id,
                last_task_id,
                last_goal,
                last_result,
                last_user_text,
                last_assistant_text,
                metadata_json
            FROM channel_states
            WHERE channel = ? AND scope = ?
            """,
            (channel, scope),
        ).fetchone()

        current = dict(row) if row else dict(defaults)
        current_metadata = _safe_json_loads(current.get("metadata_json", "{}"), {})
        merged_metadata = dict(current_metadata)
        if metadata:
            merged_metadata.update(metadata)

        if active_task_id is not None:
            current["active_task_id"] = str(active_task_id or "")[:255]
        if last_task_id is not None:
            current["last_task_id"] = str(last_task_id or "")[:255]
        if last_goal is not None:
            current["last_goal"] = str(last_goal or "")[:4000]
        if last_result is not None:
            current["last_result"] = str(last_result or "")[:4000]
        if last_user_text is not None:
            current["last_user_text"] = str(last_user_text or "")[:4000]
        if last_assistant_text is not None:
            current["last_assistant_text"] = str(last_assistant_text or "")[:4000]

        conn.execute(
            """
            INSERT INTO channel_states (
                channel,
                scope,
                updated_at,
                active_task_id,
                last_task_id,
                last_goal,
                last_result,
                last_user_text,
                last_assistant_text,
                metadata_json
            )
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel, scope) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP,
                active_task_id = excluded.active_task_id,
                last_task_id = excluded.last_task_id,
                last_goal = excluded.last_goal,
                last_result = excluded.last_result,
                last_user_text = excluded.last_user_text,
                last_assistant_text = excluded.last_assistant_text,
                metadata_json = excluded.metadata_json
            """,
            (
                channel,
                scope,
                current["active_task_id"],
                current["last_task_id"],
                current["last_goal"],
                current["last_result"],
                current["last_user_text"],
                current["last_assistant_text"],
                json.dumps(merged_metadata, ensure_ascii=False),
            ),
        )
        conn.commit()


def get_channel_state(channel: str, scope: str = "") -> dict:
    init_runtime_store()
    channel = str(channel or "").strip().lower()
    scope = str(scope or "").strip()
    if not channel:
        return {}

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                channel,
                scope,
                updated_at,
                active_task_id,
                last_task_id,
                last_goal,
                last_result,
                last_user_text,
                last_assistant_text,
                metadata_json
            FROM channel_states
            WHERE channel = ? AND scope = ?
            """,
            (channel, scope),
        ).fetchone()

    if not row:
        return {}

    result = dict(row)
    result["metadata"] = _safe_json_loads(result.get("metadata_json", "{}"), {})
    return result


def get_task_run(task_id: str) -> dict:
    init_runtime_store()
    task_id = str(task_id or "").strip()
    if not task_id:
        return {}

    with _connect() as conn:
        row = conn.execute(
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
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    if not row:
        return {}

    result = dict(row)
    result["metadata"] = _safe_json_loads(result.get("metadata_json", "{}"), {})
    return result


def recent_channel_states(limit: int = 6) -> list[dict]:
    init_runtime_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                channel,
                scope,
                updated_at,
                active_task_id,
                last_task_id,
                last_goal,
                last_result,
                last_user_text,
                last_assistant_text,
                metadata_json
            FROM channel_states
            ORDER BY updated_at DESC, channel, scope
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    results = []
    for row in rows:
        data = dict(row)
        data["metadata"] = _safe_json_loads(data.get("metadata_json", "{}"), {})
        results.append(data)
    return results


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
    results = []
    for row in rows:
        data = dict(row)
        data["metadata"] = _safe_json_loads(data.get("metadata_json", "{}"), {})
        results.append(data)
    return results


def list_task_steps(task_id: str, revision: int | None = None, limit: int | None = None) -> list[dict]:
    init_runtime_store()
    task_id = str(task_id or "").strip()
    if not task_id:
        return []

    clauses = ["task_id = ?"]
    params: list = [task_id]

    if revision is not None:
        clauses.append("revision = ?")
        params.append(int(revision))

    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(int(limit))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                task_id,
                revision,
                step_index,
                created_at,
                updated_at,
                tool,
                description,
                status,
                parameters_json,
                result_text,
                error_text,
                metadata_json
            FROM task_steps
            WHERE {' AND '.join(clauses)}
            ORDER BY revision DESC, step_index ASC{limit_sql}
            """,
            tuple(params),
        ).fetchall()

    results = []
    for row in rows:
        data = dict(row)
        data["parameters"] = _safe_json_loads(data.get("parameters_json", "{}"), {})
        data["metadata"] = _safe_json_loads(data.get("metadata_json", "{}"), {})
        results.append(data)
    return results


def recent_task_events(task_id: str = "", limit: int = 20) -> list[dict]:
    init_runtime_store()
    task_id = str(task_id or "").strip()
    with _connect() as conn:
        if task_id:
            rows = conn.execute(
                """
                SELECT id, task_id, created_at, phase, topic, content, metadata_json
                FROM task_events
                WHERE task_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (task_id, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, task_id, created_at, phase, topic, content, metadata_json
                FROM task_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

    results = []
    for row in rows:
        data = dict(row)
        data["metadata"] = _safe_json_loads(data.get("metadata_json", "{}"), {})
        results.append(data)
    return results


def record_tool_trace(
    tool: str,
    args: dict | None = None,
    result_text: str = "",
    success: bool = True,
    duration_ms: float = 0.0,
    channel: str = "",
    scope: str = "",
    source: str = "",
    error_text: str = "",
    metadata: dict | None = None,
) -> int:
    init_runtime_store()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tool_traces (
                tool,
                args_json,
                result_text,
                success,
                duration_ms,
                channel,
                scope,
                source,
                error_text,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(tool or "unknown").strip() or "unknown",
                json.dumps(args or {}, ensure_ascii=False),
                str(result_text or "")[:12000],
                int(bool(success)),
                float(duration_ms or 0.0),
                str(channel or "").strip().lower(),
                str(scope or "").strip(),
                str(source or "").strip(),
                str(error_text or "")[:4000],
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def recent_tool_traces(
    limit: int = 20,
    tool: str = "",
    success: bool | None = None,
) -> list[dict]:
    init_runtime_store()
    clauses = []
    params: list = []

    tool_name = str(tool or "").strip()
    if tool_name:
        clauses.append("tool = ?")
        params.append(tool_name)
    if success is not None:
        clauses.append("success = ?")
        params.append(int(bool(success)))

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                created_at,
                tool,
                args_json,
                result_text,
                success,
                duration_ms,
                channel,
                scope,
                source,
                error_text,
                metadata_json
            FROM tool_traces
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()

    results = []
    for row in rows:
        data = dict(row)
        data["args"] = _safe_json_loads(data.get("args_json", "{}"), {})
        data["metadata"] = _safe_json_loads(data.get("metadata_json", "{}"), {})
        data["success"] = bool(data.get("success", 0))
        results.append(data)
    return results


def recent_conversation_turns(limit: int = 8, channel: str = "", channel_scope: str = "") -> list[dict]:
    init_runtime_store()
    channel = str(channel or "").strip().lower()
    channel_scope = str(channel_scope or "").strip()
    with _connect() as conn:
        if channel:
            rows = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    user_text,
                    assistant_text,
                    keywords_json,
                    channel,
                    channel_scope,
                    metadata_json
                FROM conversation_turns
                WHERE channel = ? AND channel_scope = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (channel, channel_scope, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    user_text,
                    assistant_text,
                    keywords_json,
                    channel,
                    channel_scope,
                    metadata_json
                FROM conversation_turns
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
    return [dict(row) for row in rows]


def search_conversation_turns(
    query: str,
    limit: int = 5,
    window: int = 250,
    channel: str = "",
    channel_scope: str = "",
) -> list[dict]:
    init_runtime_store()
    channel = str(channel or "").strip().lower()
    channel_scope = str(channel_scope or "").strip()
    terms = set(_tokenize(query))
    if not terms:
        return recent_conversation_turns(limit=limit, channel=channel, channel_scope=channel_scope)

    match_query = _fts_match_query(query)
    with _connect() as conn:
        if match_query:
            try:
                if channel:
                    rows = conn.execute(
                        """
                        SELECT
                            c.id,
                            c.created_at,
                            c.user_text,
                            c.assistant_text,
                            c.keywords_json,
                            c.channel,
                            c.channel_scope,
                            c.metadata_json,
                            bm25(conversation_turns_fts) AS score
                        FROM conversation_turns_fts
                        JOIN conversation_turns c ON conversation_turns_fts.rowid = c.id
                        WHERE conversation_turns_fts MATCH ?
                          AND c.channel = ?
                          AND c.channel_scope = ?
                        ORDER BY score ASC, c.id DESC
                        LIMIT ?
                        """,
                        (match_query, channel, channel_scope, int(limit)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT
                            c.id,
                            c.created_at,
                            c.user_text,
                            c.assistant_text,
                            c.keywords_json,
                            c.channel,
                            c.channel_scope,
                            c.metadata_json,
                            bm25(conversation_turns_fts) AS score
                        FROM conversation_turns_fts
                        JOIN conversation_turns c ON conversation_turns_fts.rowid = c.id
                        WHERE conversation_turns_fts MATCH ?
                        ORDER BY score ASC, c.id DESC
                        LIMIT ?
                        """,
                        (match_query, int(limit)),
                    ).fetchall()
                return [dict(row) for row in rows]
            except sqlite3.OperationalError:
                pass

        if channel:
            rows = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    user_text,
                    assistant_text,
                    keywords_json,
                    channel,
                    channel_scope,
                    metadata_json
                FROM conversation_turns
                WHERE channel = ? AND channel_scope = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (channel, channel_scope, int(window)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    user_text,
                    assistant_text,
                    keywords_json,
                    channel,
                    channel_scope,
                    metadata_json
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


def search_graph_memory(query: str, limit: int = 5) -> list[dict]:
    init_runtime_store()
    query_terms = set(_tokenize(query))
    if not query_terms:
        return recent_graph_relations(limit=limit)

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                r.id,
                r.created_at,
                r.updated_at,
                r.relation,
                r.evidence,
                r.metadata_json,
                s.name AS source_name,
                s.kind AS source_kind,
                t.name AS target_name,
                t.kind AS target_kind
            FROM graph_relations r
            JOIN graph_entities s ON s.id = r.source_entity_id
            JOIN graph_entities t ON t.id = r.target_entity_id
            ORDER BY r.updated_at DESC, r.id DESC
            LIMIT ?
            """,
            (max(int(limit) * 10, 40),),
        ).fetchall()

    scored: list[tuple[int, int, dict]] = []
    for row in rows:
        data = dict(row)
        haystack = (
            f"{data.get('source_name', '')}\n"
            f"{data.get('relation', '')}\n"
            f"{data.get('target_name', '')}\n"
            f"{data.get('evidence', '')}"
        ).lower()
        score = sum(1 for token in query_terms if token in haystack)
        if score <= 0:
            continue
        scored.append((score, int(data["id"]), data))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[: int(limit)]]
