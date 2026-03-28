import json
import re
from threading import Lock
from pathlib import Path
import sys

from memory.runtime_store import (
    log_conversation_turn,
    recent_channel_states,
    recent_graph_relations,
    recent_conversation_turns,
    recent_events,
    search_graph_memory,
    search_knowledge_items,
    search_conversation_turns,
    upsert_knowledge_item,
)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"
_lock       = Lock()

MAX_VALUE_LENGTH = 300


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        fallback = str(text or "").encode("ascii", "replace").decode("ascii", errors="replace")
        print(fallback)


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "relationships": {},
        "notes":         {},
        "nexus_knowledge": {}
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()

    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return _empty_memory()
        except Exception as e:
            _safe_print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False

    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            if isinstance(value, dict) and "value" in value:
                entry = {"value": _truncate_value(str(value["value"]))}
            else:
                entry = {"value": _truncate_value(str(value))}

            if key not in target or target[key] != entry:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:

    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    memory = load_memory()

    if _recursive_update(memory, memory_update):
        save_memory(memory)
        _safe_print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")

    return memory


# --- MEMORY ARCHIVE FUNCTIONS ---

def save_to_nexus(
    topic: str,
    content: str,
    kind: str = "archive",
    source: str = "memory.long_term",
    metadata: dict | None = None,
) -> bool:
    memory = load_memory()
    if "nexus_knowledge" not in memory:
        memory["nexus_knowledge"] = {}
    
    memory["nexus_knowledge"][topic] = content
    save_memory(memory)
    _safe_print(f"[Archive] Saved knowledge: {topic}")
    try:
        from memory.runtime_store import log_event

        upsert_knowledge_item(
            kind=str(kind or "archive"),
            title=str(topic or "untitled"),
            content=str(content or "")[:12000],
            source=str(source or "memory.long_term"),
            metadata=metadata or {},
        )
        log_event(
            "archive",
            topic,
            str(content)[:2000],
            metadata={
                "kind": str(kind or "archive"),
                "source": str(source or "memory.long_term"),
            },
        )
    except Exception:
        pass
    return True


def remember_conversation_turn(
    user_text: str,
    axiom_text: str = "",
    channel: str = "",
    channel_scope: str = "",
    metadata: dict | None = None,
) -> None:
    try:
        log_conversation_turn(
            user_text,
            axiom_text,
            channel=channel,
            channel_scope=channel_scope,
            metadata=metadata,
        )
    except Exception as e:
        _safe_print(f"[Memory] ⚠️ Conversation archive error: {e}")

def get_from_nexus(topic: str) -> str:
    memory = load_memory()
    knowledge = memory.get("nexus_knowledge", {})
    return knowledge.get(topic, "")

def list_nexus_topics() -> list:
    memory = load_memory()
    return list(memory.get("nexus_knowledge", {}).keys())


def save_to_memory_archive(
    topic: str,
    content: str,
    kind: str = "knowledge",
    source: str = "memory.long_term",
    metadata: dict | None = None,
) -> bool:
    return save_to_nexus(topic, content, kind=kind, source=source, metadata=metadata)


def get_from_memory_archive(topic: str) -> str:
    return get_from_nexus(topic)


def list_memory_topics() -> list:
    return list_nexus_topics()


def search_memory_archive(query: str, limit: int = 5) -> dict:
    memory = load_memory()
    knowledge = memory.get("nexus_knowledge", {})
    query_terms = {
        token for token in re.findall(r"[a-zA-Z0-9_'-]+", str(query or "").lower())
        if len(token) >= 4
    }

    indexed_hits = search_knowledge_items(query, limit=max(int(limit) * 2, 8))
    indexed_results = []
    nexus_results = []
    seen_titles = set()
    for item in indexed_hits:
        title = str(item.get("title", "")).strip()
        content = str(item.get("content", "")).strip()
        kind = str(item.get("kind", "general") or "general").strip() or "general"
        source = str(item.get("source", "")).strip()
        if not title or not content:
            continue
        seen_titles.add(title.lower())
        indexed_results.append(
            {
                "topic": title,
                "title": title,
                "kind": kind,
                "source": source,
                "content": content[:1200],
            }
        )
        if kind in {"nexus", "archive"} and len(nexus_results) < int(limit):
            nexus_results.append(
                {
                    "topic": title,
                    "content": content[:1200],
                    "kind": kind,
                    "source": source,
                }
            )

    nexus_hits = []
    for topic, content in knowledge.items():
        if str(topic).lower() in seen_titles:
            continue
        haystack = f"{topic}\n{content}".lower()
        score = sum(1 for token in query_terms if token in haystack)
        if score > 0:
            nexus_hits.append((score, topic, content))
    nexus_hits.sort(key=lambda item: item[0], reverse=True)

    for _, topic, content in nexus_hits:
        if len(nexus_results) >= int(limit):
            break
        nexus_results.append({"topic": topic, "content": str(content)[:1200]})

    return {
        "knowledge": indexed_results[: max(int(limit), 8)],
        "archive": nexus_results,
        "nexus": nexus_results,
        "graph": search_graph_memory(query, limit=limit),
        "conversations": search_conversation_turns(query, limit=limit),
    }


def recall_relevant_context(goal: str, limit: int = 5) -> str:
    """
    Search across all memory sources for context relevant to a goal.
    Returns a formatted string ready for injection into planner/executor prompts.

    This is the key function that makes AXIOM's memory *actively* drive decisions
    instead of just passively recording.
    """
    goal_text = str(goal or "").strip()
    if not goal_text:
        return ""

    sections = []

    # 1. Search knowledge items (task strategies, lessons, archived knowledge)
    try:
        results = search_memory_archive(goal_text, limit=limit)

        knowledge = results.get("knowledge", [])
        if knowledge:
            k_lines = ["[PRIOR KNOWLEDGE]"]
            for item in knowledge[:limit]:
                title = str(item.get("title", "")).strip()
                content = str(item.get("content", "")).strip()
                kind = str(item.get("kind", "")).strip()
                if title and content:
                    k_lines.append(f"- [{kind}] {title}: {content[:300]}")
            if len(k_lines) > 1:
                sections.append("\n".join(k_lines))

        # 2. Graph memory relations
        graph = results.get("graph", [])
        if graph:
            g_lines = ["[RELATED FACTS]"]
            for item in graph[:4]:
                source = str(item.get("source_name", "")).strip()
                relation = str(item.get("relation", "")).strip().replace("_", " ")
                target = str(item.get("target_name", "")).strip()
                if source and relation and target:
                    g_lines.append(f"- {source} → {relation} → {target}")
            if len(g_lines) > 1:
                sections.append("\n".join(g_lines))

        # 3. Recent relevant conversations
        conversations = results.get("conversations", [])
        if conversations:
            c_lines = ["[RELEVANT PAST CONVERSATIONS]"]
            for item in conversations[:3]:
                user_text = str(item.get("user_text", "")).strip()
                ai_text = str(item.get("assistant_text", "")).strip()
                if user_text:
                    c_lines.append(f"- User: {user_text[:200]}")
                    if ai_text:
                        c_lines.append(f"  Axiom: {ai_text[:200]}")
            if len(c_lines) > 1:
                sections.append("\n".join(c_lines))

    except Exception as e:
        _safe_print(f"[Memory] ⚠️ Context recall failed: {e}")

    # 4. User preferences
    try:
        memory = load_memory()
        prefs = memory.get("preferences", {})
        pref_lines = []
        for key, entry in list(prefs.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                pref_lines.append(f"- {key.replace('_', ' ').title()}: {val}")
        if pref_lines:
            sections.append("[USER PREFERENCES]\n" + "\n".join(pref_lines))
    except Exception:
        pass

    context = "\n\n".join(sections)
    if len(context) > 2400:
        context = context[:2397] + "..."
    return context



def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    def _format_turn_label(row: dict) -> str:
        channel = str(row.get("channel", "") or "").strip().lower()
        scope = str(row.get("channel_scope", "") or "").strip()
        if channel == "telegram":
            return f"Telegram {scope}" if scope else "Telegram"
        if channel == "voice":
            return "Voice"
        return "Archive"

    # Identity
    identity = memory.get("identity", {})
    name = identity.get("name", {}).get("value")
    age  = identity.get("age",  {}).get("value")
    bday = identity.get("birthday", {}).get("value")
    city = identity.get("city", {}).get("value")
    if name: lines.append(f"Name: {name}")
    if age:  lines.append(f"Age: {age}")
    if bday: lines.append(f"Birthday: {bday}")
    if city: lines.append(f"City: {city}")

    prefs = memory.get("preferences", {})
    for i, (key, entry) in enumerate(prefs.items()):
        if i >= 5:
            break
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    for i, (key, entry) in enumerate(rels.items()):
        if i >= 5:
            break
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.title()}: {val}")

    notes = memory.get("notes", {})
    for i, (key, entry) in enumerate(notes.items()):
        if i >= 5:
            break
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key}: {val}")

    sections = []
    if lines:
        sections.append("[USER MEMORY]\n" + "\n".join(f"- {l}" for l in lines))

    topics = list_nexus_topics()
    if topics:
        nexus_lines = [f"Archived topics: {', '.join(topics[:12])}"]
        latest_topic = topics[-1]
        latest_content = get_from_nexus(latest_topic)
        if latest_content:
            nexus_lines.append(f"Latest archived note ({latest_topic}): {latest_content[:420]}...")

        recent_nexus = []
        seen_topics = set()
        for row in recent_events(limit=20):
            topic = str(row.get("topic", "")).strip()
            kind = str(row.get("kind", "")).strip().lower()
            if not topic or topic in seen_topics:
                continue
            if kind not in {"archive", "nexus"}:
                continue
            seen_topics.add(topic)
            recent_nexus.append(f"- {topic}: {str(row.get('content', ''))[:180]}")
            if len(recent_nexus) >= 4:
                break
        if recent_nexus:
            nexus_lines.append("Recent archived knowledge:")
            nexus_lines.extend(recent_nexus)

        nexus_lines.append("Use `memory_archive` with action='search' or 'recall' for deeper retrieval.")
        sections.append("[MEMORY ARCHIVE]\n" + "\n".join(nexus_lines))

    graph_rows = recent_graph_relations(limit=5)
    if graph_rows:
        graph_lines = []
        for row in graph_rows:
            source = str(row.get("source_name", "")).strip()
            relation = str(row.get("relation", "")).strip().replace("_", " ")
            target = str(row.get("target_name", "")).strip()
            evidence = str(row.get("evidence", "")).strip()
            if not source or not relation or not target:
                continue
            line = f"- {source} -> {relation} -> {target}"
            if evidence:
                line += f" | evidence: {evidence[:120]}"
            graph_lines.append(line)
        if graph_lines:
            sections.append(
                "[GRAPH MEMORY]\n"
                "Linked facts and components remembered across sessions.\n"
                + "\n".join(graph_lines[:5])
            )

    channel_rows = recent_channel_states(limit=4)
    if channel_rows:
        handoff_lines = []
        for row in channel_rows:
            channel = str(row.get("channel", "")).strip().lower()
            if channel not in {"telegram", "voice"}:
                continue
            label = "Telegram" if channel == "telegram" else "Voice"
            last_goal = str(row.get("last_goal", "")).strip()
            last_result = str(row.get("last_result", "")).strip()
            active_task_id = str(row.get("active_task_id", "")).strip()
            if active_task_id and last_goal:
                handoff_lines.append(f"- {label} active task: {last_goal[:160]}")
            elif last_goal and last_result:
                handoff_lines.append(
                    f"- {label} last task: {last_goal[:120]} -> {last_result[:180]}"
                )
        if handoff_lines:
            sections.append(
                "[CHANNEL HANDOFFS]\n"
                "Recent voice and Telegram execution state shared across channels.\n"
                + "\n".join(handoff_lines[:4])
            )

    recent_turns = list(reversed(recent_conversation_turns(limit=4)))
    if recent_turns:
        convo_lines = []
        for row in recent_turns:
            user_text = str(row.get("user_text", "")).strip()
            ai_text = str(row.get("assistant_text", "")).strip()
            label = _format_turn_label(row)
            convo_lines.append(f"- [{label}] User: {user_text[:180]}")
            if ai_text:
                convo_lines.append(f"  Axiom: {ai_text[:180]}")
        sections.append(
            "[RECENT CONVERSATION ARCHIVE]\n"
            "This is durable cross-session recall from earlier interactions.\n"
            + "\n".join(convo_lines)
        )

    if not sections:
        return ""

    result = "\n\n".join(sections)
    if len(result) > 3200:
        result = result[:3197] + "…"

    return result + "\n"
