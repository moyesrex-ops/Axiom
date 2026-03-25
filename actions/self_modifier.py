# actions/self_modifier.py
# AXIOM — Self-Modification & Dynamic Capability Registration
#
# Allows Axiom to:
#   1. Read its own source files (actions/, agent/, core/, memory/).
#   2. Write new Python scripts into the actions/ directory.
#   3. Dynamically register them so they become callable tools at runtime.
#   4. Log every self-modification to the Nexus Brain for permanent awareness.

import json
import sys
import importlib
import inspect
import re
from pathlib import Path

from core.runtime_config import get_voice_name, update_runtime_config


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_api_key() -> str:
    path = _get_base_dir() / "config" / "api_keys.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]
    except Exception:
        return ""


# ── safe directory whitelist ──────────────────────────────────────────────────

_ALLOWED_READ_DIRS = ["actions", "agent", "core", "memory"]
_ACTIONS_DIR = _get_base_dir() / "actions"

# Registry of dynamically loaded modules: { tool_name: callable }
_DYNAMIC_REGISTRY: dict = {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_safe_path(rel_path: str) -> Path | None:
    """Resolve a relative path only if it falls within allowed directories."""
    base = _get_base_dir()
    target = (base / rel_path).resolve()
    for allowed in _ALLOWED_READ_DIRS:
        if target.is_relative_to((base / allowed).resolve()):
            return target
    return None


# ── core operations ───────────────────────────────────────────────────────────

def read_source(file_path: str) -> str:
    """Read an Axiom source file. Only allowed within safe directories."""
    path = _resolve_safe_path(file_path)
    if path is None:
        return f"[SelfModifier] Access denied: '{file_path}' is outside allowed directories."
    if not path.exists():
        return f"[SelfModifier] File not found: {file_path}"
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[SelfModifier] Read error: {e}"


def write_new_action(tool_name: str, description: str, code: str) -> str:
    """
    Write a new Python file into actions/ and dynamically register it.

    Parameters
    ----------
    tool_name   : snake_case name for the new tool (e.g. 'send_email')
    description : What the tool does (saved to Nexus Brain)
    code        : Full Python source code for the new actions/<tool_name>.py file
    """
    # Sanitise tool name
    safe_name = re.sub(r"[^a-z0-9_]", "_", tool_name.lower())
    if not safe_name:
        return "[SelfModifier] Invalid tool name."

    target_path = _ACTIONS_DIR / f"{safe_name}.py"

    if target_path.exists():
        return (
            f"[SelfModifier] Tool '{safe_name}' already exists at {target_path}. "
            "Use action='edit_action' to modify it."
        )

    try:
        target_path.write_text(code, encoding="utf-8")
        print(f"[SelfModifier] ✅ New action written: {target_path}")
    except Exception as e:
        return f"[SelfModifier] Write failed: {e}"

    # Dynamic import & registration
    reg_result = _register_tool(safe_name)

    # Nexus Brain: log the self-modification
    try:
        from memory.memory_manager import save_to_nexus
        save_to_nexus(
            f"Self-Modification: {safe_name}",
            f"New tool '{safe_name}' created. Description: {description}\n"
            f"File: actions/{safe_name}.py"
        )
    except Exception:
        pass

    return (
        f"[SelfModifier] Tool '{safe_name}' created and {reg_result}. "
        "It is available to AXIOM's task/executor path immediately. "
        "Direct live-model tool calling may require a session restart so the tool schema refreshes."
    )


def edit_action(tool_name: str, new_code: str) -> str:
    """Overwrite an existing action file with new code."""
    safe_name = re.sub(r"[^a-z0-9_]", "_", tool_name.lower())
    target_path = _ACTIONS_DIR / f"{safe_name}.py"

    if not target_path.exists():
        return f"[SelfModifier] Tool '{safe_name}' not found. Use action='write_action' to create it."

    try:
        target_path.write_text(new_code, encoding="utf-8")
        reg_result = _register_tool(safe_name)
        try:
            from memory.memory_manager import save_to_nexus
            save_to_nexus(
                f"Self-Edit: {safe_name}",
                f"Tool '{safe_name}' was edited and reloaded."
            )
        except Exception:
            pass
        return (
            f"[SelfModifier] Tool '{safe_name}' updated and {reg_result}. "
            "Executor access updates immediately; direct live-model tool exposure may require a session restart."
        )
    except Exception as e:
        return f"[SelfModifier] Edit failed: {e}"


def list_actions() -> str:
    """List all Python files in the actions/ directory."""
    files = sorted(_ACTIONS_DIR.glob("*.py"))
    if not files:
        return "No action files found."
    lines = [f.stem for f in files if not f.stem.startswith("__")]
    return "Available actions:\n" + "\n".join(f"  • {n}" for n in lines)


def _register_tool(module_name: str) -> str:
    """Dynamically import or reload a module from actions/ and register its entry point."""
    try:
        fqn = f"actions.{module_name}"
        if fqn in sys.modules:
            mod = importlib.reload(sys.modules[fqn])
        else:
            mod = importlib.import_module(fqn)

        # Convention: the entry function shares the module name
        entry_func = getattr(mod, module_name, None)
        if entry_func and callable(entry_func):
            _DYNAMIC_REGISTRY[module_name] = entry_func
            return f"registered as callable tool '{module_name}'"
        return "loaded (no matching entry function found — module available)"
    except Exception as e:
        return f"load failed: {e}"


def get_dynamic_tool(tool_name: str):
    """Return a dynamically registered tool callable, or None."""
    return _DYNAMIC_REGISTRY.get(tool_name)


def generate_action_with_ai(
    tool_name: str,
    description: str,
    speak=None,
) -> str:
    """
    Ask Gemini to write a new action file from scratch, then register it.
    """
    if speak:
        speak(f"Generating new capability: {tool_name}. Writing code now.")

    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        existing_example = read_source("actions/weather_report.py")
        prompt = f"""
You are a Python engineer contributing to the Axiom AI assistant framework.
Create a new action module for the Axiom codebase.

TOOL NAME: {tool_name}
DESCRIPTION: {description}

CONVENTIONS (follow exactly):
- Entry function must be named `{tool_name}(parameters: dict = None, player=None, speak=None) -> str`
- All heavy imports inside the function or wrapped in try/except ImportError
- On success return a human-readable result string
- On failure return a descriptive error string (do NOT raise)
- Save important results to nexus using:
  from memory.memory_manager import save_to_nexus
  save_to_nexus("topic", "content")

EXAMPLE EXISTING ACTION (for style reference):
```python
{existing_example[:1500]}
```

OUTPUT: Return ONLY the raw Python source code. No markdown fences, no explanation.
"""

        response = model.generate_content(prompt)
        code = response.text.strip()
        # Strip any accidental markdown fences
        code = re.sub(r"^```(?:python)?", "", code, flags=re.MULTILINE).strip()
        code = re.sub(r"```$", "", code, flags=re.MULTILINE).strip()

        return write_new_action(tool_name, description, code)

    except Exception as e:
        return f"[SelfModifier] AI code generation failed: {e}"


# ── Voice change ─────────────────────────────────────────────────────────────

_AVAILABLE_VOICES = [
    "Aoede", "Charon", "Fenrir", "Kore", "Leda", "Orus", "Puck",
    "Schedar", "Umbriel", "Zephyr", "Achird", "Algenib", "Algieba",
    "Alnilam", "Autonoe", "Callirrhoe", "Despina", "Enceladus",
    "Erinome", "Gacrux", "Iocaste", "Laomedeia", "Lysithea",
    "Megaclite", "Mundilfari", "Nereid", "Oberon", "Rasalgethi",
    "Sadachbia", "Sadaltager", "Sulafat", "Thuban", "Vindemiatrix",
    "Wasat", "Zubenelgenubi"
]


def change_voice(voice_name: str) -> str:
    requested = voice_name.strip().title()
    matched = next((v for v in _AVAILABLE_VOICES if v.lower() == requested.lower()), None)
    if matched is None:
        matched = next((v for v in _AVAILABLE_VOICES if v.lower().startswith(requested.lower())), None)
    if matched is None:
        return (
            f"[SelfModifier] Voice '{voice_name}' not found. "
            f"Available voices: {', '.join(_AVAILABLE_VOICES)}"
        )

    current = get_voice_name()
    if current.lower() == matched.lower():
        return f"[SelfModifier] Voice is already set to '{matched}'."

    update_runtime_config({"voice_name": matched})
    try:
        from memory.memory_manager import save_to_nexus
        from memory.runtime_store import log_event

        save_to_nexus("Voice Setting", f"Voice changed to '{matched}'.")
        log_event("self_modifier", "voice_change", f"Voice changed to {matched}")
    except Exception:
        pass
    return (
        f"Voice changed to '{matched}'. "
        "This takes effect on the next live-session reconnect."
    )


# ── main entry point ─────────────────────────────────────────────────────────

def self_modifier(parameters: dict = None, player=None, speak=None) -> str:
    """
    AXIOM Self-Modification Engine.

    actions:
        read_source    — Read a source file. Requires: file_path
        write_action   — Write new tool from raw code. Requires: tool_name, code, description
        edit_action    — Edit existing tool. Requires: tool_name, new_code
        generate_action— AI-generate new tool. Requires: tool_name, description
        list_actions   — List all action files
        change_voice   — Change the live voice. Requires: voice_name
        list_voices    — List all available live voices
    """
    params = parameters or {}
    action = params.get("action", "list_actions").strip().lower()

    # Log this meta-action to nexus
    try:
        from memory.memory_manager import save_to_nexus
        save_to_nexus("Last Self-Modifier Call", f"action={action}, params_keys={list(params.keys())}")
    except Exception:
        pass

    if action == "read_source":
        file_path = params.get("file_path", "")
        if not file_path:
            return "[SelfModifier] 'file_path' is required for read_source."
        return read_source(file_path)

    elif action == "write_action":
        tool_name   = params.get("tool_name", "")
        code        = params.get("code", "")
        description = params.get("description", "")
        if not tool_name or not code:
            return "[SelfModifier] 'tool_name' and 'code' are required for write_action."
        return write_new_action(tool_name, description, code)

    elif action == "edit_action":
        tool_name = params.get("tool_name", "")
        new_code  = params.get("new_code", "")
        if not tool_name or not new_code:
            return "[SelfModifier] 'tool_name' and 'new_code' are required for edit_action."
        return edit_action(tool_name, new_code)

    elif action == "generate_action":
        tool_name   = params.get("tool_name", "")
        description = params.get("description", "")
        if not tool_name or not description:
            return "[SelfModifier] 'tool_name' and 'description' are required for generate_action."
        return generate_action_with_ai(tool_name, description, speak=speak)

    elif action == "list_actions":
        return list_actions()

    elif action == "change_voice":
        voice_name = params.get("voice_name", params.get("value", ""))
        if not voice_name:
            return "[SelfModifier] 'voice_name' is required for change_voice."
        return change_voice(voice_name)

    elif action == "list_voices":
        return "Available voices: " + ", ".join(_AVAILABLE_VOICES)

    else:
        return (
            f"[SelfModifier] Unknown action: '{action}'. "
            "Use read_source | write_action | edit_action | generate_action | "
            "list_actions | change_voice | list_voices."
        )
