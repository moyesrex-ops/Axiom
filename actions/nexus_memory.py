import json
from memory.memory_manager import save_to_nexus, get_from_nexus, list_nexus_topics

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
        
    return f"Unknown action: {action}. Use 'save', 'recall', or 'list'."
