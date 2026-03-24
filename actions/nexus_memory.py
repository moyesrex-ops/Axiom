import json
from memory.memory_manager import (
    save_to_nexus,
    get_from_nexus,
    list_nexus_topics,
    recent_conversation_turns,
    search_memory_archive,
)

def nexus_memory(parameters: dict, player=None) -> str:
    """Action module for saving and recalling from the Nexus Brain."""
    action = parameters.get("action", "")
    
    if action == "save":
        topic = parameters.get("topic")
        content = parameters.get("content")
        if not topic or not content:
            return "Error: Both 'topic' and 'content' are required for saving to Nexus."
        
        success = save_to_nexus(topic, content)
        return "Knowledge successfully saved to Nexus Brain." if success else "Failed to save to Nexus."
        
    elif action == "recall":
        topic = parameters.get("topic")
        if not topic:
            return "Error: 'topic' is required for recalling from Nexus."
            
        content = get_from_nexus(topic)
        if content:
            return f"--- NEXUS KNOWLEDGE: {topic.upper()} ---\n{content}\n--- END NEXUS ---"
        else:
            topics = list_nexus_topics()
            suggest = f" Available topics: {', '.join(topics)}" if topics else " The Nexus Brain is currently empty."
            return f"Topic '{topic}' not found in Nexus Brain.{suggest}"
            
    elif action == "list":
        topics = list_nexus_topics()
        if topics:
            return f"Nexus Brain contains knowledge on: {', '.join(topics)}"
        return "The Nexus Brain is currently empty."

    elif action == "recent":
        rows = list(reversed(recent_conversation_turns(limit=int(parameters.get("limit", 5) or 5))))
        if not rows:
            return "No archived conversation turns yet."
        lines = ["Recent archived conversation turns"]
        for row in rows:
            lines.append(f"- User: {str(row.get('user_text', ''))[:160]}")
            if row.get("assistant_text"):
                lines.append(f"  Axiom: {str(row.get('assistant_text', ''))[:160]}")
        return "\n".join(lines)

    elif action == "search":
        query = str(parameters.get("query", "")).strip()
        if not query:
            return "Error: 'query' is required for memory search."

        results = search_memory_archive(query, limit=int(parameters.get("limit", 5) or 5))
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

        nexus_hits = results.get("nexus", [])
        if nexus_hits:
            lines.append("Nexus matches:")
            for item in nexus_hits:
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
