import json
from memory.memory_manager import (
    save_to_nexus,
    get_from_nexus,
    list_nexus_topics,
    recent_conversation_turns,
    search_memory_archive,
)


def memory_archive(parameters: dict, player=None) -> str:
    """Action module for AXIOM's durable memory archive."""
    action = str((parameters or {}).get("action", "")).strip().lower()

    if action == "save":
        topic = (parameters or {}).get("topic")
        content = (parameters or {}).get("content")
        if not topic or not content:
            return "Error: Both 'topic' and 'content' are required for memory save."

        success = save_to_nexus(topic, content)
        return "Knowledge saved to memory archive." if success else "Failed to save to memory archive."

    elif action == "recall":
        topic = (parameters or {}).get("topic")
        if not topic:
            return "Error: 'topic' is required for memory recall."

        content = get_from_nexus(topic)
        if content:
            return f"--- MEMORY ARCHIVE: {str(topic).upper()} ---\n{content}\n--- END ARCHIVE ---"
        else:
            topics = list_nexus_topics()
            suggest = f" Available topics: {', '.join(topics)}" if topics else " The memory archive is currently empty."
            return f"Topic '{topic}' was not found in memory archive.{suggest}"

    elif action == "list":
        topics = list_nexus_topics()
        if topics:
            return f"Memory archive topics: {', '.join(topics)}"
        return "The memory archive is currently empty."

    elif action == "recent":
        rows = list(reversed(recent_conversation_turns(limit=int((parameters or {}).get("limit", 5) or 5))))
        if not rows:
            return "No archived conversation turns yet."
        lines = ["Recent archived conversation turns"]
        for row in rows:
            lines.append(f"- User: {str(row.get('user_text', ''))[:160]}")
            if row.get("assistant_text"):
                lines.append(f"  Axiom: {str(row.get('assistant_text', ''))[:160]}")
        return "\n".join(lines)

    elif action == "search":
        query = str((parameters or {}).get("query", "")).strip()
        if not query:
            return "Error: 'query' is required for memory search."

        results = search_memory_archive(query, limit=int((parameters or {}).get("limit", 5) or 5))
        lines = [f"Memory search results for: {query}"]

        knowledge_hits = results.get("knowledge", [])
        if knowledge_hits:
            lines.append("Indexed knowledge matches:")
            for item in knowledge_hits[:5]:
                label = item.get("topic") or item.get("title") or "untitled"
                kind = str(item.get("kind", "general")).strip() or "general"
                source = str(item.get("source", "")).strip()
                suffix = f" [{kind}]" if kind else ""
                if source:
                    suffix += f" <{source}>"
                lines.append(f"- {label}{suffix}: {str(item.get('content', ''))[:180]}")

        archive_hits = results.get("archive", []) or results.get("nexus", [])
        if archive_hits:
            lines.append("Archive matches:")
            for item in archive_hits:
                lines.append(f"- {item['topic']}: {item['content'][:180]}")

        convo_hits = results.get("conversations", [])
        if convo_hits:
            lines.append("Conversation matches:")
            for row in convo_hits:
                lines.append(f"- User: {str(row.get('user_text', ''))[:160]}")
                if row.get("assistant_text"):
                    lines.append(f"  Axiom: {str(row.get('assistant_text', ''))[:160]}")

        if len(lines) == 1:
            return "No relevant memory matches found."
        return "\n".join(lines)

    return f"Unknown action: {action}. Use 'save', 'recall', 'list', 'recent', or 'search'."


def nexus_memory(parameters: dict, player=None) -> str:
    """Backward-compatible alias for older plans/tool calls."""
    return memory_archive(parameters=parameters, player=player)
