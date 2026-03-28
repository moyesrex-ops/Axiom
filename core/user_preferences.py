# core/user_preferences.py
# AXIOM — Centralized User Preference System
#
# Provides a unified interface for reading and writing user preferences.
# Preferences are backed by both long_term.json and the SQLite knowledge_items
# table, ensuring they survive across sessions and are searchable.

import sys
from pathlib import Path


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# ── Preference Read/Write ──────────────────────────────────────────────


def get_preference(key: str, default: str = "") -> str:
    """
    Get a user preference by key. Checks long_term.json preferences first,
    then falls back to knowledge_items search.
    """
    key = str(key or "").strip()
    if not key:
        return default

    # Check long_term.json first (fastest)
    try:
        from memory.memory_manager import load_memory
        memory = load_memory()
        prefs = memory.get("preferences", {})

        # Direct key match
        entry = prefs.get(key)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                return str(val)

        # Try normalized key (underscores, lowercase)
        normalized = key.lower().replace(" ", "_").replace("-", "_")
        entry = prefs.get(normalized)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                return str(val)
    except Exception:
        pass

    # Fall back to knowledge_items search
    try:
        from memory.runtime_store import search_knowledge_items
        results = search_knowledge_items(key, limit=1, kinds=["preference", "user_preference"])
        if results:
            return str(results[0].get("content", default) or default).strip()
    except Exception:
        pass

    return default


def set_preference(key: str, value: str) -> None:
    """
    Save a user preference. Persists to both long_term.json and knowledge_items.
    """
    key = str(key or "").strip()
    value = str(value or "").strip()
    if not key:
        return

    normalized_key = key.lower().replace(" ", "_").replace("-", "_")

    # Save to long_term.json
    try:
        from memory.memory_manager import update_memory
        update_memory({"preferences": {normalized_key: value}})
    except Exception as e:
        print(f"[Preferences] ⚠️ Memory save failed: {e}")

    # Also save to knowledge_items for searchability
    try:
        from memory.runtime_store import upsert_knowledge_item, log_event
        upsert_knowledge_item(
            kind="user_preference",
            title=f"Preference: {key}",
            content=value,
            source="core.user_preferences",
            metadata={"key": normalized_key},
        )
        log_event("preferences", "set", f"{key} = {value[:200]}")
    except Exception:
        pass


# ── Specific Preference Helpers ────────────────────────────────────────


def get_browser_preference() -> str:
    """
    Get the user's preferred browser name.
    Returns empty string if no preference is set.
    """
    return get_preference("preferred_browser") or get_preference("browser")


def set_browser_preference(browser_name: str) -> None:
    """Set the user's preferred browser."""
    set_preference("preferred_browser", browser_name)


def get_media_preferences() -> dict:
    """Get user's media/music preferences as a dict."""
    prefs = {}
    for key in ("favorite_music_genre", "preferred_music", "music_taste",
                "favorite_genre", "media_preference"):
        val = get_preference(key)
        if val:
            prefs[key] = val
    return prefs


def get_all_preferences() -> dict:
    """Get all user preferences as a flat dict."""
    try:
        from memory.memory_manager import load_memory
        memory = load_memory()
        prefs = memory.get("preferences", {})
        result = {}
        for key, entry in prefs.items():
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                result[key] = str(val)
        return result
    except Exception:
        return {}
