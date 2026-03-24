import json
import re
from threading import Lock
from pathlib import Path
import sys

from memory.runtime_store import (
    log_conversation_turn,
    recent_conversation_turns,
    recent_events,
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
            print(f"[Memory] ⚠️ Load error: {e}")
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
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")

    return memory


# --- NEXUS BRAIN FUNCTIONS ---

def save_to_nexus(
    topic: str,
    content: str,
    kind: str = "nexus",
    source: str = "memory.long_term",
    metadata: dict | None = None,
) -> bool:
    memory = load_memory()
    if "nexus_knowledge" not in memory:
        memory["nexus_knowledge"] = {}
    
    memory["nexus_knowledge"][topic] = content
    save_memory(memory)
    print(f"[Nexus] 🧠 Saved new knowledge: {topic}")
    try:
        from memory.runtime_store import log_event

        upsert_knowledge_item(
            kind=str(kind or "nexus"),
            title=str(topic or "untitled"),
            content=str(content or "")[:12000],
            source=str(source or "memory.long_term"),
            metadata=metadata or {},
        )
        log_event(
            "nexus",
            topic,
            str(content)[:2000],
            metadata={
                "kind": str(kind or "nexus"),
                "source": str(source or "memory.long_term"),
            },
        )
    except Exception:
        pass
    return True


def remember_conversation_turn(user_text: str, axiom_text: str = "") -> None:
    try:
        log_conversation_turn(user_text, axiom_text)
    except Exception as e:
        print(f"[Memory] ⚠️ Conversation archive error: {e}")

def get_from_nexus(topic: str) -> str:
    memory = load_memory()
    knowledge = memory.get("nexus_knowledge", {})
    return knowledge.get(topic, "")

def list_nexus_topics() -> list:
    memory = load_memory()
    return list(memory.get("nexus_knowledge", {}).keys())


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
        if kind == "nexus" and len(nexus_results) < int(limit):
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
        "nexus": nexus_results,
        "conversations": search_conversation_turns(query, limit=limit),
    }



def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

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
        nexus_lines = [f"Known topics: {', '.join(topics[:12])}"]
        latest_topic = topics[-1]
        latest_content = get_from_nexus(latest_topic)
        if latest_content:
            nexus_lines.append(f"Latest recall ({latest_topic}): {latest_content[:420]}...")

        recent_nexus = []
        seen_topics = set()
        for row in recent_events(limit=10, kind="nexus"):
            topic = str(row.get("topic", "")).strip()
            if not topic or topic in seen_topics:
                continue
            seen_topics.add(topic)
            recent_nexus.append(f"- {topic}: {str(row.get('content', ''))[:180]}")
            if len(recent_nexus) >= 4:
                break
        if recent_nexus:
            nexus_lines.append("Recent learned knowledge:")
            nexus_lines.extend(recent_nexus)

        nexus_lines.append("Use `nexus_memory` with action='search' or 'recall' for deeper retrieval.")
        sections.append("[NEURAL LINK: NEXUS BRAIN]\n" + "\n".join(nexus_lines))

    recent_turns = list(reversed(recent_conversation_turns(limit=4)))
    if recent_turns:
        convo_lines = []
        for row in recent_turns:
            user_text = str(row.get("user_text", "")).strip()
            ai_text = str(row.get("assistant_text", "")).strip()
            convo_lines.append(f"- User: {user_text[:180]}")
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
