import asyncio
import atexit
import threading
import json
import re
import sys
import traceback
from pathlib import Path

import pyaudio
import numpy as np
from google import genai
from google.genai import types
import time
from ui import AxiomUI
from memory.memory_manager import (
    load_memory,
    update_memory,
    format_memory_for_prompt,
    remember_conversation_turn,
)

from agent.task_queue import get_queue

from actions.flight_finder import flight_finder
from actions.open_app         import open_app
from actions.weather_report   import weather_action
from actions.send_message     import send_message
from actions.reminder         import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor import screen_process
from actions.youtube_video    import youtube_video
from actions.cmd_control      import cmd_control
from actions.desktop          import desktop_control
from actions.browser_control  import browser_control, shutdown_browser_control
from actions.file_controller  import file_controller
from actions.code_helper      import code_helper
from actions.codex_builder    import codex_builder
from actions.dev_agent        import dev_agent
from actions.web_search       import web_search as web_search_action
from actions.computer_control import computer_control
from actions.nexus_memory     import memory_archive
from actions.deep_analyzer    import deep_analyzer
from actions.autonomous_researcher import autonomous_research
from actions.mt5_trading_agent     import mt5_trading
from actions.market_predictor      import predict_market
from actions.mirofish_control      import mirofish_control
from actions.tradingagents_control import tradingagents_control
from actions.automaton_control     import automaton_control
from actions.autoresearch_control  import autoresearch_control
from actions.deerflow_control      import deerflow_control
from actions.lightpanda_control    import lightpanda_control
from actions.self_modifier         import self_modifier, get_dynamic_tool
from actions.skill_library         import skill_library
from actions.agent_library         import agent_library
from actions.system_capabilities   import system_capabilities
from actions.dexter_control        import dexter_control
from actions.pentagi_control       import pentagi_control
from actions.persona_control       import persona_control
from actions.prompt_studio         import prompt_studio
from actions.lead_researcher       import lead_researcher
from actions.swarm_orchestrator    import swarm_orchestrator
from agent.heartbeat               import HeartbeatDaemon
from core.capabilities             import format_capability_status
from core.doctor                   import boot_doctor_lines
from core.integration_manager      import boot_integrations
from core.runtime_config           import load_runtime_config
from core.secret_config            import get_secret
from core.system_context           import format_prompt_system_context
from core.telegram_bridge          import start_telegram_bridge, stop_telegram_bridge
from memory.runtime_store          import init_runtime_store, log_event

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
DEFAULT_LIVE_MODEL  = "models/gemini-2.5-flash-native-audio-preview-12-2025"
FORMAT              = pyaudio.paInt16
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

pya = pyaudio.PyAudio()

def _get_api_key() -> str:
    return get_secret("gemini_api_key", ["GEMINI_API_KEY"])

def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are AXIOM, an advanced AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results - always call the appropriate tool."
        )

_memory_turn_counter  = 0
_memory_turn_lock     = threading.Lock()
_MEMORY_EVERY_N_TURNS = 5
_last_memory_input    = ""


def _summarize_exception(error: BaseException, depth: int = 0) -> str:
    if error is None:
        return "unknown error"

    nested = getattr(error, "exceptions", None)
    if nested and depth < 2:
        parts = []
        for child in list(nested)[:4]:
            child_text = _summarize_exception(child, depth + 1)
            if child_text and child_text not in parts:
                parts.append(child_text)
        prefix = error.__class__.__name__
        if parts:
            return f"{prefix}: " + " | ".join(parts)

    text = str(error or "").strip()
    if text:
        return f"{error.__class__.__name__}: {text}"
    return error.__class__.__name__


def _is_clean_rotation_error(error: BaseException) -> bool:
    text = _summarize_exception(error).lower()
    return "connectionclosedok" in text or "sent 1000 (ok)" in text or "received 1000 (ok)" in text


def _is_invalid_resumption_error(error: BaseException) -> bool:
    text = _summarize_exception(error).lower()
    return "1008" in text and ("not implemented" in text or "session resumption" in text or "operation is not implemented" in text)


def _update_memory_async(user_text: str, axiom_text: str) -> None:
    global _memory_turn_counter, _last_memory_input

    remember_conversation_turn(user_text, axiom_text)

    with _memory_turn_lock:
        _memory_turn_counter += 1
        current_count = _memory_turn_counter

    if current_count % _MEMORY_EVERY_N_TURNS != 0:
        return

    text = user_text.strip()
    if len(text) < 10:
        return
    if text == _last_memory_input:
        return
    _last_memory_input = text

    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash-lite")

        check = model.generate_content(
            f"Does this message contain personal facts about the user "
            f"(name, age, city, job, hobby, relationship, birthday, preference)? "
            f"Reply only YES or NO.\n\nMessage: {text[:300]}"
        )
        if "YES" not in check.text.upper():
            return

        raw = model.generate_content(
            f"Extract personal facts from this message. Any language.\n"
            f"Return ONLY valid JSON or {{}} if nothing found.\n"
            f"Extract: name, age, birthday, city, job, hobbies, preferences, relationships, language.\n"
            f"Skip: weather, reminders, search results, commands.\n\n"
            f"Format:\n"
            f'{{"identity":{{"name":{{"value":"..."}}}}}}, '
            f'"preferences":{{"hobby":{{"value":"..."}}}}, '
            f'"notes":{{"job":{{"value":"..."}}}}}}\n\n'
            f"Message: {text[:500]}\n\nJSON:"
        ).text.strip()

        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        if not raw or raw == "{}":
            return

        data = json.loads(raw)
        if data:
            update_memory(data)
            print(f"[Memory] Updated: {list(data.keys())}")

    except json.JSONDecodeError:
        pass
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] Warning: {e}")


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool - never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
{
    "name": "web_search",
    "description": "Searches the web for any information. Use mode='deep' for Perplexity-style multi-source research. If a Vane backend is configured it may be used automatically for cited deep answers. Use mode='social' with query=URL to analyze a Reddit/Twitter/X page and extract strategies.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query":   {"type": "STRING", "description": "Search query or URL (for social mode)"},
            "mode":    {"type": "STRING", "description": "search (default) | compare | deep | social"},
            "items":   {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
            "aspect":  {"type": "STRING", "description": "price | specs | reviews"},
            "context": {"type": "STRING", "description": "What to extract/analyze or emphasize (for deep/social mode)"},
            "sources": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optional source filters for deep/Vane research: web | discussions | academic"}
        },
        "required": ["query"]
    }
},
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
    "name": "youtube_video",
    "description": (
        "Controls YouTube. Use for: playing videos, replacing the current playing video in the same controlled tab, "
        "checking the current YouTube/browser playback state, summarizing a video's content, "
        "getting video info, or showing trending videos. Prefer this tool over generic browser search for YouTube playback."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "play | summarize | get_info | trending | state (default: play)"
            },
            "query":  {"type": "STRING", "description": "Search query for play action"},
            "kind":   {"type": "STRING", "description": "For play action: video | shorts | auto. Use video unless the user explicitly asks for Shorts."},
            "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
            "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
            "url":    {"type": "STRING", "description": "Video URL for get_info or direct play action"},
        },
        "required": []
    }
    },
    {
        "name": "screen_process",
        "description": (
            "Analyzes the user's screen or their webcam using Gemini Vision. "
            "Use when the user asks 'what is on my screen', 'read this', or 'explain what you see'. "
            "CRITICAL: If the user explicitly asks you to 'look at me', 'use the camera', or 'what am I holding', "
            "you MUST set the angle parameter to 'camera' so you can see them directly through their webcam!"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {
                    "type": "STRING",
                    "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"
                },
                "text": {
                    "type": "STRING",
                    "description": "The question or instruction about the captured image"
                }
            },
            "required": ["text"]
        }
    },
    {
    "name": "computer_settings",
    "description": (
        "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
        "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
        "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
        "ALSO controls physical RGB hardware lighting (keyboard/mouse color) - use action: change_hardware_color with value: red/blue/green/glowing/off etc. "
        "ALSO inspects local hardware state - use action: hardware_status or gpu_status to inspect CPU, memory, disk, battery, GPU, and RGB bridge status. "
        "ALSO can open device manager - use action: open_device_manager. "
        "ALSO use for safely force-closing a specific app/process by name WITHOUT crashing Axiom - "
        "use action: force_close, value: <process_name>. "
        "ALSO use for repeated actions: 'refresh 10 times', 'reload page 5 times' -> action: reload_n, value: 10. "
        "Use for ANY single computer control command - even if repeated N times. "
        "NEVER route simple computer commands to agent_task."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "The action to perform (if known). For repeated reload: 'reload_n'. For RGB: 'change_hardware_color'. For killing a process: 'force_close'."},
            "description": {"type": "STRING", "description": "Natural language description of what to do"},
            "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, number of times, color name (red/blue/glowing/etc.), or process name for force_close"}
        },
        "required": []
    }
},
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, finding cheapest products, "
            "booking flights, inspecting the current page/tab state, closing the current tab, "
            "or handling any web-based task that needs awareness of what is already open."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | current_state | close_tab | youtube_play | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "kind":        {"type": "STRING", "description": "youtube_play only: video | shorts | auto"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders. Use for: listing files, creating/deleting/moving/copying "
            "files, reading file contents, finding files by name or extension, checking disk usage, "
            "organizing the desktop, getting file info."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "cmd_control",
        "description": (
            "Runs CMD/terminal commands by understanding natural language. "
            "Use when user wants to: find large files, check disk space, list processes, "
            "get system info, navigate folders, check network, find files by name, "
            "or do ANYTHING in the command line they don't know how to do themselves."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":    {"type": "STRING", "description": "Natural language description of what to do. Example: 'find the 10 largest files on C drive'"},
                "visible": {"type": "BOOLEAN", "description": "Open visible CMD window so user can see. Default: true"},
                "command": {"type": "STRING", "description": "Optional: exact command if already known"},
            },
            "required": ["task"]
        }
    },
    {
        "name": "desktop_control",
        "description": (
            "Controls the desktop. Use for: changing wallpaper, organizing desktop files, "
            "cleaning the desktop, listing desktop contents, or ANY other desktop-related task "
            "the user describes in natural language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language description of any desktop task"},
            },
            "required": ["action"]
        }
    },
    {
    "name": "code_helper",
    "description": (
        "Writes, edits, explains, or runs focused code files. "
        "Use for single-file scripts, targeted file fixes, code explanation, or quick code execution. "
        "Use codex_builder for polished multi-file websites, apps, or playable games."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
            "description": {"type": "STRING", "description": "What the code should do, or what change to make"},
            "language":    {"type": "STRING", "description": "Programming language (default: python)"},
            "output_path": {"type": "STRING", "description": "Where to save the file (full path or filename)"},
            "file_path":   {"type": "STRING", "description": "Path to existing file for edit / explain / run / build"},
            "code":        {"type": "STRING", "description": "Raw code string for explain"},
            "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
            "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
        },
        "required": ["action"]
    }
    },
    {
    "name": "codex_builder",
    "description": (
        "Builds real runnable projects using Codex CLI. "
        "Use this for polished websites, apps, playable games, and multi-file builds where the user needs a real artifact path, run command, or open target."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":        {"type": "STRING", "description": "build | status"},
            "description":   {"type": "STRING", "description": "What to build"},
            "project_name":  {"type": "STRING", "description": "Optional project folder name"},
            "project_path":  {"type": "STRING", "description": "Optional explicit project path"},
            "model":         {"type": "STRING", "description": "Optional Codex model override"},
            "timeout":       {"type": "INTEGER", "description": "Build timeout in seconds"},
            "open_when_done":{"type": "BOOLEAN", "description": "Open the primary artifact when finished"},
        },
        "required": ["action"]
    }
    },
    {
    "name": "dev_agent",
    "description": (
        "Legacy multi-file project builder. "
        "Prefer codex_builder for new runnable websites, apps, and games. "
        "Use this only if Codex is unavailable and a fallback project build is still needed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description":  {"type": "STRING", "description": "What the project should do"},
            "language":     {"type": "STRING", "description": "Programming language (default: python)"},
            "project_name": {"type": "STRING", "description": "Optional project folder name"},
            "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
        },
        "required": ["description"]
    }
    },
    {
    "name": "agent_task",
    "description": (
        "Executes complex multi-step tasks that require MULTIPLE DIFFERENT tools. "
        "Always respond to the user in the language they spoke. "
        "Examples: 'research X and save to file', 'find files and organize them', "
        "'fill a form on a website', 'write and test code'. "
        "DO NOT use for simple computer commands like volume, refresh, close, scroll, "
        "minimize, screenshot, restart, shutdown - use computer_settings for those. "
        "DO NOT use if the task can be done with a single tool call."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {
                "type": "STRING",
                "description": "Complete description of what needs to be accomplished"
            },
            "priority": {
                "type": "STRING",
                "description": "low | normal | high (default: normal)"
            }
        },
        "required": ["goal"]
    }
},
    {
    "name": "computer_control",
    "description": (
        "Direct computer control: type text, click buttons, use keyboard shortcuts, "
        "scroll, move mouse, take screenshots, fill forms, find elements on screen. "
        "Use when the user wants to interact with any app on the computer directly. "
        "Can generate random data for forms or use user's real info from memory."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
            "text":        {"type": "STRING", "description": "Text to type or paste"},
            "x":           {"type": "INTEGER", "description": "X coordinate for click/move"},
            "y":           {"type": "INTEGER", "description": "Y coordinate for click/move"},
            "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
            "key":         {"type": "STRING", "description": "Single key to press e.g. 'enter'"},
            "direction":   {"type": "STRING", "description": "Scroll direction: up | down | left | right"},
            "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
            "seconds":     {"type": "NUMBER", "description": "Seconds to wait"},
            "title":       {"type": "STRING", "description": "Window title for focus_window"},
            "description": {"type": "STRING", "description": "Element description for screen_find/screen_click"},
            "type":        {"type": "STRING", "description": "Data type for random_data: name|email|username|password|phone|birthday|address"},
            "field":       {"type": "STRING", "description": "Field for user_data: name|email|city"},
            "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            "path":        {"type": "STRING", "description": "Save path for screenshot"},
        },
        "required": ["action"]
    }
},

{
    "name": "flight_finder",
    "description": (
        "Searches for flights on Google Flights and speaks the best options. "
        "Use when user asks about flights, plane tickets, etc."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "origin":       {"type": "STRING",  "description": "Departure city or airport code"},
            "destination":  {"type": "STRING",  "description": "Arrival city or airport code"},
            "date":         {"type": "STRING",  "description": "Departure date (any format)"},
            "return_date":  {"type": "STRING",  "description": "Return date for round trips"},
            "passengers":   {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
            "cabin":        {"type": "STRING",  "description": "economy | premium | business | first"},
            "save":         {"type": "BOOLEAN", "description": "Save results to Notepad"},
        },
        "required": ["origin", "destination", "date"]
    }
},
{
    "name": "memory_archive",
    "description": (
        "Saves, recalls, lists, searches, or reviews archived long-term knowledge from AXIOM's durable memory archive. "
        "Use this to permanently memorize learned skills, preferences, strategies, "
        "or code snippets so you never forget them. Before attempting complex tasks, "
        "you can use this to recall how you were told to do them previously, including older conversation turns."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":  {"type": "STRING", "description": "save | recall | list | recent | search"},
            "topic":   {"type": "STRING", "description": "Topic name (e.g., 'trading_strategy_A', 'my_code_preferences')"},
            "content": {"type": "STRING", "description": "The detailed content to save (required for save action)"},
            "query":   {"type": "STRING", "description": "Search query for memory search"},
            "limit":   {"type": "INTEGER", "description": "Maximum number of results to return"}
        },
        "required": ["action"]
    }
},
{
    "name": "deep_analyzer",
    "description": (
        "Performs deep MULTIMODAL video analysis using Gemini's massive context window. "
        "Use this ONLY when the user explicitly asks to 'watch this YouTube video', "
        "'analyze this chart over time', or wants deep visual insight into a video feed. "
        "Unlike youtube_video (which only reads text transcripts), this tool actually WATCHES the visual footage."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":   {"type": "STRING", "description": "youtube (download a video) or screen (record user screen)"},
            "url":      {"type": "STRING", "description": "YouTube URL if action is youtube"},
            "duration": {"type": "INTEGER", "description": "Seconds to record if action is screen (10-30)"},
            "prompt":   {"type": "STRING", "description": "What specifically to analyze or look for"}
        },
        "required": ["action", "prompt"]
    }
},
{
    "name": "autonomous_researcher",
    "description": (
        "Mass-ingests an entire YouTube channel or playlist, extracts all transcripts, "
        "and uses Gemini's 2M token context window to synthesize the ultimate strategy. "
        "Use this exclusively when the user says 'watch every video on this channel', "
        "'learn his entire account', 'find the perfect strategy from his videos', etc. "
        "It will automatically save the knowledge to the memory archive without you needing to do it."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "url":   {"type": "STRING", "description": "The URL to the YouTube channel or playlist."},
            "query": {"type": "STRING", "description": "What exactly to synthesize (e.g. 'Extract his exact trading strategy, entry/exit, psychology')"}
        },
        "required": ["url", "query"]
    }
},
{
    "name": "mt5_trading",
    "description": (
        "Natively executes ultra-low latency Buy/Sell orders on MetaTrader 5 via C++ socket bindings. "
        "Supports stop-loss and take-profit levels. After each trade closes, Axiom automatically "
        "reflects on the result and stores the lesson in memory to continuously improve. "
        "Use this exclusively when the user says 'start trading', 'buy EURUSD', 'sell 0.5 lots', etc."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "The action to perform: 'info', 'buy', or 'sell'."},
            "symbol":      {"type": "STRING", "description": "The market symbol to trade (e.g., 'EURUSD'). Default is EURUSD."},
            "volume":      {"type": "NUMBER", "description": "The lot size for the trade (e.g., 0.01). Default is 0.01."},
            "stop_loss":   {"type": "NUMBER", "description": "Optional stop-loss price. Defaults to a 50-pip protective stop if omitted."},
            "take_profit": {"type": "NUMBER", "description": "Optional take-profit price. Defaults to a 50-pip target if omitted."},
            "prompt":      {"type": "STRING", "description": "Natural language trade intent for AI extraction."}
        },
        "required": ["action"]
    }
},
{
    "name": "predict_market",
    "description": (
        "Runs AXIOM's market swarm and, when available, layers in real MiroFish seed/report context "
        "to predict the trajectory of a market asset. Use source='axiom' to skip MiroFish or "
        "source='mirofish' to strongly prefer that external context. Use source='tradingagents' "
        "to run the imported TradingAgents sidecar for a real multi-agent market analysis."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "asset": {"type": "STRING", "description": "The asset to predict (e.g., 'Bitcoin', 'EURUSD')."},
            "context": {"type": "STRING", "description": "Any specific news, timeframes, or biases the user provided."},
            "source": {"type": "STRING", "description": "auto | axiom | mirofish | tradingagents"},
            "trade_date": {"type": "STRING", "description": "Optional analysis date for TradingAgents in YYYY-MM-DD format"},
            "provider": {"type": "STRING", "description": "Optional TradingAgents provider override"},
            "deep_model": {"type": "STRING", "description": "Optional TradingAgents deep model override"},
            "quick_model": {"type": "STRING", "description": "Optional TradingAgents quick model override"},
            "analysts": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Optional TradingAgents analyst subset: market, social, news, fundamentals"
            }
        },
        "required": ["asset"]
    }
},
{
    "name": "mirofish_control",
    "description": (
        "Inspects and controls the external MiroFish runtime. Use this to check real MiroFish health, "
        "list projects/simulations/reports, pull market seed context, configure paths, or launch the backend."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | projects | simulations | reports | market_seed | configure | start_backend | launch_instructions"},
            "asset": {"type": "STRING", "description": "Market asset for market_seed"},
            "repo_path": {"type": "STRING", "description": "Optional local MiroFish repo path"},
            "server_url": {"type": "STRING", "description": "Optional MiroFish backend URL"},
            "auto_start": {"type": "BOOLEAN", "description": "Whether MiroFish should auto-start when supported"},
            "limit": {"type": "INTEGER", "description": "Optional row/result limit"}
        },
        "required": ["action"]
    }
},
{
    "name": "tradingagents_control",
    "description": (
        "Inspects, prepares, and runs the imported TradingAgents sidecar. Use this to check runtime readiness, "
        "prepare its isolated uv environment, inspect logged runs, configure defaults, or run a real market analysis."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | runs | configure | prepare | analyze | execute_mt5 | launch_instructions"},
            "repo_path": {"type": "STRING", "description": "Optional local TradingAgents repo path"},
            "ticker": {"type": "STRING", "description": "Ticker symbol for analyze"},
            "trade_date": {"type": "STRING", "description": "Analysis date in YYYY-MM-DD format for analyze"},
            "provider": {"type": "STRING", "description": "Optional provider override, default google"},
            "deep_model": {"type": "STRING", "description": "Optional deep model override"},
            "quick_model": {"type": "STRING", "description": "Optional quick model override"},
            "analysts": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optional analyst subset"},
            "max_debate_rounds": {"type": "INTEGER", "description": "Optional investment debate rounds"},
            "max_risk_discuss_rounds": {"type": "INTEGER", "description": "Optional risk debate rounds"},
            "timeout": {"type": "INTEGER", "description": "Optional prepare or analysis timeout in seconds"},
            "limit": {"type": "INTEGER", "description": "Optional result limit for runs"},
            "symbol": {"type": "STRING", "description": "Optional MT5 symbol override for execute_mt5"},
            "volume": {"type": "NUMBER", "description": "Optional live order size for execute_mt5"},
            "confirm": {"type": "BOOLEAN", "description": "Explicitly allow live MT5 execution for execute_mt5"},
            "dry_run": {"type": "BOOLEAN", "description": "Force analysis plus handoff preview without live execution"},
            "min_confidence": {"type": "INTEGER", "description": "Optional minimum confidence threshold for live execution"},
            "max_volume": {"type": "NUMBER", "description": "Optional hard cap for live execution volume"},
            "allowed_symbols": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optional allow-list for execute_mt5 symbols"}
        },
        "required": ["action"]
    }
},
{
    "name": "self_modifier",
    "description": (
        "Axiom's self-modification engine. Allows Axiom to read its own source code, "
        "write new Python action scripts into the actions/ directory, edit existing ones, "
        "or use AI to generate entirely new capabilities on the fly. "
        "Newly registered tools become available to AXIOM's executor immediately; direct live-tool exposure may require a session refresh. "
        "ALSO allows Axiom to change its own voice using action='change_voice' with voice_name=<name>. "
        "Use action='list_voices' to see all available voice names. "
        "Use when the user asks Axiom to add a new skill, grant itself a new tool, "
        "edit its own behavior, change its voice, or list available actions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "read_source | write_action | edit_action | generate_action | list_actions | change_voice | list_voices"
            },
            "file_path":    {"type": "STRING", "description": "Relative path to source file (for read_source)"},
            "tool_name":    {"type": "STRING", "description": "Snake_case name for the new/existing tool"},
            "description":  {"type": "STRING", "description": "What the tool should do (for generate_action / write_action)"},
            "code":         {"type": "STRING", "description": "Raw Python source code (for write_action)"},
            "new_code":     {"type": "STRING", "description": "Replacement Python source code (for edit_action)"},
            "voice_name":   {"type": "STRING", "description": "Voice name for change_voice (e.g. Puck, Fenrir, Kore, Aoede, Charon)"}
        },
        "required": ["action"]
    }
},
{
    "name": "skill_library",
    "description": (
        "Searches and reads integrated external skill libraries from Everything Claude Code, "
        "Superpowers, Antigravity, DeerFlow, and local skills. Use this for coding workflows, debugging patterns, "
        "testing playbooks, review checklists, or implementation strategy references."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | sources | search | recommend | read"},
            "query": {"type": "STRING", "description": "Search query or task description"},
            "task": {"type": "STRING", "description": "Task description for recommend"},
            "skill": {"type": "STRING", "description": "Skill id or name for read"},
            "source": {"type": "STRING", "description": "Optional source id filter"},
            "limit": {"type": "INTEGER", "description": "Optional result limit"},
            "save": {"type": "BOOLEAN", "description": "Whether to save results to memory"}
        },
        "required": []
    }
},
{
    "name": "agent_library",
    "description": (
        "Searches, reads, recommends, and supervises imported specialist agent catalogs, including "
        "frontend, backend, design, research, security, studio, and strategy roles. "
        "Use this when AXIOM should choose specialist agents or delegate a task to them."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | sources | search | recommend | read | delegate"},
            "query": {"type": "STRING", "description": "Search query or task description"},
            "task": {"type": "STRING", "description": "Task description for recommend or delegate"},
            "agent": {"type": "STRING", "description": "Agent id or name for read"},
            "agents": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Optional list of agent ids or names for delegate"
            },
            "source": {"type": "STRING", "description": "Optional source id filter"},
            "limit": {"type": "INTEGER", "description": "Optional result or delegation limit"},
            "model": {"type": "STRING", "description": "Optional reasoning model override for delegate"},
            "context": {"type": "STRING", "description": "Optional extra context for delegate"},
            "content_limit": {"type": "INTEGER", "description": "Optional text limit for read"},
            "save": {"type": "BOOLEAN", "description": "Whether to save results to memory"}
        },
        "required": []
    }
},
{
    "name": "system_capabilities",
    "description": (
        "Inspects Axiom's current environment, installed integrations, recent runtime events, "
        "recorded failures, hardware snapshot, local timezone, and best-effort location context. "
        "Use when the user asks what Axiom can do right now or asks where they are / what timezone they are in."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "summary | status | doctor | context | hardware | integrations | mirofish | automaton | dexter | pentagi | tradingagents | lightpanda | autoresearch | deerflow | skills | agents | failures | events | tasks"},
            "limit":  {"type": "INTEGER", "description": "Optional row limit for failures/events/tasks"}
        },
        "required": []
    }
},
{
    "name": "automaton_control",
    "description": (
        "Inspects the external Conway Automaton runtime and state directory. Use this to check whether "
        "Automaton is actually built and initialized, inspect its memory/heartbeat counts, read SOUL.md, "
        "configure repo/state paths, start the runtime, or get launch instructions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | memory | state | soul | configure | start_runtime | launch_instructions"},
            "repo_path": {"type": "STRING", "description": "Optional local Automaton repo path"},
            "state_dir": {"type": "STRING", "description": "Optional Automaton state directory"},
            "auto_start": {"type": "BOOLEAN", "description": "Whether Automaton should auto-start during AXIOM boot when launchable"},
            "limit": {"type": "INTEGER", "description": "Optional text limit for soul action"}
        },
        "required": ["action"]
    }
},
{
    "name": "dexter_control",
    "description": (
        "Inspects the imported Dexter financial research runtime and setup. Use this to check repo health, "
        "configure the repo path, or get real launch instructions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | configure | launch_instructions"},
            "repo_path": {"type": "STRING", "description": "Optional local Dexter repo path"}
        },
        "required": ["action"]
    }
},
{
    "name": "pentagi_control",
    "description": (
        "Inspects the imported PentAGI security runtime status. Use this to check whether the repo is actually "
        "runnable, configure the repo path, or get honest launch instructions when upstream source is unavailable."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | configure | launch_instructions"},
            "repo_path": {"type": "STRING", "description": "Optional local PentAGI repo path"}
        },
        "required": ["action"]
    }
},
{
    "name": "lightpanda_control",
    "description": (
        "Inspects and configures the optional Lightpanda browser backend. Use this to check "
        "CDP endpoint readiness, backend selection, repo path, launch it when provisioned, "
        "or get launch instructions for faster browser automation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | endpoint | configure | start | launch_instructions"},
            "backend": {"type": "STRING", "description": "playwright | lightpanda"},
            "endpoint": {"type": "STRING", "description": "CDP endpoint such as http://127.0.0.1:9222"},
            "repo_path": {"type": "STRING", "description": "Optional Lightpanda repo path"},
            "auto_connect": {"type": "BOOLEAN", "description": "Whether browser_control should try Lightpanda automatically"},
            "auto_start": {"type": "BOOLEAN", "description": "Whether AXIOM should try to boot Lightpanda during startup when possible"},
            "timeout": {"type": "NUMBER", "description": "Optional startup timeout in seconds"}
        },
        "required": ["action"]
    }
},
{
    "name": "autoresearch_control",
    "description": (
        "Inspects and configures the local autoresearch repo. Use this to check research-loop readiness, "
        "read program.md, inspect results.tsv, prepare the repo, train it, or get launch instructions for real autonomous ML experiments."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | program | results | configure | prepare | train | launch_instructions"},
            "repo_path": {"type": "STRING", "description": "Optional autoresearch repo path"},
            "limit": {"type": "INTEGER", "description": "Optional row/result limit"},
            "content_limit": {"type": "INTEGER", "description": "Optional text limit for program"},
            "save": {"type": "BOOLEAN", "description": "Whether to save results to memory"},
            "timeout": {"type": "INTEGER", "description": "Optional prepare/train timeout in seconds"}
        },
        "required": ["action"]
    }
},
{
    "name": "deerflow_control",
    "description": (
        "Inspects and optionally queries the local DeerFlow super-agent harness. Use this to check "
        "whether DeerFlow is live, configure repo or URLs, run a deep delegated query through its API, "
        "or get launch instructions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | configure | query | launch_instructions"},
            "repo_path": {"type": "STRING", "description": "Optional DeerFlow repo path"},
            "url": {"type": "STRING", "description": "Optional DeerFlow base URL, usually http://127.0.0.1:2026"},
            "gateway_url": {"type": "STRING", "description": "Optional DeerFlow gateway URL"},
            "langgraph_url": {"type": "STRING", "description": "Optional DeerFlow LangGraph URL"},
            "prompt": {"type": "STRING", "description": "Prompt for DeerFlow query"},
            "query": {"type": "STRING", "description": "Alternate prompt field for DeerFlow query"},
            "goal": {"type": "STRING", "description": "Alternate prompt field for DeerFlow query"},
            "mode": {"type": "STRING", "description": "flash | standard | pro | ultra"},
            "thread_id": {"type": "STRING", "description": "Optional DeerFlow thread id to continue"},
            "timeout": {"type": "INTEGER", "description": "Optional query timeout in seconds"},
            "limit": {"type": "INTEGER", "description": "Optional status row limit"}
        },
        "required": ["action"]
    }
},
{
    "name": "persona_control",
    "description": (
        "Configures optional NVIDIA PersonaPlex integration for full-duplex personality and voice control. "
        "Use to inspect status, enable/disable it, or get launch instructions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":       {"type": "STRING", "description": "status | enable | disable | configure | launch_instructions"},
            "server_url":   {"type": "STRING", "description": "PersonaPlex websocket URL"},
            "repo_path":    {"type": "STRING", "description": "Local PersonaPlex repo path"},
            "text_prompt":  {"type": "STRING", "description": "PersonaPlex role prompt"},
            "voice_prompt": {"type": "STRING", "description": "PersonaPlex voice prompt file or label"},
            "cpu_offload":  {"type": "BOOLEAN", "description": "Whether PersonaPlex should use CPU offload"},
            "auto_start":   {"type": "BOOLEAN", "description": "Whether PersonaPlex should auto-start when supported"}
        },
        "required": ["action"]
    }
},
{
    "name": "prompt_studio",
    "description": (
        "Designs elite prompts for image generation, video generation, creative direction, and prompt optimization. "
        "Use when the user wants strong prompts or visual ideation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "medium":       {"type": "STRING", "description": "image | video | branding | concept"},
            "idea":         {"type": "STRING", "description": "The concept to build prompts for"},
            "style":        {"type": "STRING", "description": "Desired art direction or style"},
            "constraints":  {"type": "STRING", "description": "Any constraints, exclusions, or technical requirements"},
            "target_model": {"type": "STRING", "description": "Optional target model or platform"}
        },
        "required": ["idea"]
    }
},
{
    "name": "lead_researcher",
    "description": (
        "Researches PUBLIC business leads and extracts public contact signals such as emails, phone numbers, and social links. "
        "Use for prospecting or public lead discovery."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query":       {"type": "STRING", "description": "Search query for the lead hunt"},
            "industry":    {"type": "STRING", "description": "Optional industry or niche"},
            "location":    {"type": "STRING", "description": "Optional target geography"},
            "site":        {"type": "STRING", "description": "Optional site/domain filter"},
            "max_results": {"type": "INTEGER", "description": "Maximum number of leads to return"}
        },
        "required": []
    }
},
{
    "name": "swarm_orchestrator",
    "description": (
        "Runs a generalized multi-role AI swarm for research, strategy, build planning, critique, "
        "or imported specialist-agent supervision. Use this when the user wants several expert viewpoints fused into one result."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal":    {"type": "STRING", "description": "The objective for the swarm"},
            "mode":    {"type": "STRING", "description": "research | strategy | build | critique | specialist"},
            "context": {"type": "STRING", "description": "Optional extra context"},
            "query":   {"type": "STRING", "description": "Optional specialist search query"},
            "agents":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optional specialist agent ids or names"},
            "source":  {"type": "STRING", "description": "Optional source id filter"},
            "limit":   {"type": "INTEGER", "description": "Optional specialist delegation limit"},
            "model":   {"type": "STRING", "description": "Optional reasoning model override"}
        },
        "required": ["goal"]
    }
}
]

class AxiomLive:

    def __init__(self, ui: AxiomUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self.live_model     = DEFAULT_LIVE_MODEL
        
        # Audio tweaks
        self.is_speaking          = False
        self.TARGET_INPUT_RMS     = 4200.0
        self.MAX_INPUT_GAIN       = 6.2
        self.MIN_INTERRUPT_RMS    = 850.0
        self._ambient_rms         = 120.0
        self._speaker_guard_until = 0.0

        self._input_turn_buffer   = []
        self._output_turn_buffer  = []
        self._disconnect_count    = 0
        self._last_disconnect_reason = ""
        self._session_resumption_handle = ""
        self._session_resumable = False
        self._go_away_requested = False
        self._shutdown_requested = threading.Event()

    def speak(self, text: str):
        """Thread-safe speak - any thread can call this."""
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
         )

    def _interrupt_threshold(self) -> float:
        return max(self.MIN_INTERRUPT_RMS, self._ambient_rms * 3.35)

    def _speaker_guard_threshold(self) -> float:
        return max(360.0, self._ambient_rms * 2.2)

    def _adaptive_gain(self, rms: float) -> float:
        if rms <= 60:
            return 1.0
        return min(self.MAX_INPUT_GAIN, max(1.0, self.TARGET_INPUT_RMS / max(rms, 1.0)))

    def _finalize_transcript_turn(self) -> None:
        full_in = " ".join(self._input_turn_buffer).strip()
        full_out = " ".join(self._output_turn_buffer).strip()

        if full_in:
            self.ui.write_log(f"You: {full_in}")
        if full_out:
            self.ui.write_log(f"Axiom: {full_out}")

        self._input_turn_buffer.clear()
        self._output_turn_buffer.clear()

        if full_in and len(full_in) > 5:
            threading.Thread(
                target=_update_memory_async,
                args=(full_in, full_out),
                daemon=True
            ).start()

    def _recover_partial_transcript(self, reason: str) -> None:
        full_in = " ".join(self._input_turn_buffer).strip()
        full_out = " ".join(self._output_turn_buffer).strip()
        self._input_turn_buffer.clear()
        self._output_turn_buffer.clear()

        if not full_in and not full_out:
            return

        if full_in:
            self.ui.write_log(f"You (recovered): {full_in}")
        if full_out:
            self.ui.write_log(f"Axiom (recovered): {full_out}")

        if full_in and len(full_in) > 5:
            remember_conversation_turn(full_in, full_out)

        log_event(
            "session",
            "partial_turn_recovered",
            reason[:500],
            metadata={
                "user_text": full_in[:240],
                "assistant_text": full_out[:240],
            },
        )

    def _note_session_resumption_update(self, update: types.LiveServerSessionResumptionUpdate) -> None:
        new_handle = str(getattr(update, "new_handle", "") or "").strip()
        resumable = bool(getattr(update, "resumable", False))
        last_index = getattr(update, "last_consumed_client_message_index", None)

        metadata = {
            "resumable": resumable,
            "last_consumed_client_message_index": last_index,
        }

        if new_handle and new_handle != self._session_resumption_handle:
            self._session_resumption_handle = new_handle
            log_event(
                "session",
                "resumption_handle_updated",
                new_handle[:48],
                metadata=metadata,
            )
        elif not new_handle and not resumable:
            self._session_resumption_handle = ""

        self._session_resumable = resumable

    def request_shutdown(self) -> None:
        if self._shutdown_requested.is_set():
            return

        self._shutdown_requested.set()
        if not self._loop or not self.session:
            return

        async def _close_session():
            try:
                await self.session.close()
            except Exception as error:
                log_event("session", "shutdown_close_error", _summarize_exception(error)[:500])

        try:
            asyncio.run_coroutine_threadsafe(_close_session(), self._loop)
        except Exception as error:
            log_event("session", "shutdown_schedule_error", _summarize_exception(error)[:500])

    async def _handle_go_away(self, go_away: types.LiveServerGoAway) -> None:
        if self._go_away_requested:
            return

        self._go_away_requested = True
        time_left = str(getattr(go_away, "time_left", "") or "").strip()
        detail = time_left or "server requested reconnect"
        self._last_disconnect_reason = f"Server requested reconnect ({detail})"
        self.ui.write_log("SYS: Live session is rotating. Reconnecting cleanly.")
        log_event(
            "session",
            "go_away",
            detail[:500],
            metadata={
                "has_resumption_handle": bool(self._session_resumption_handle),
                "resumable": self._session_resumable,
            },
        )
        try:
            if self.session:
                await self.session.close()
        except Exception as close_error:
            log_event("session", "go_away_close_error", _summarize_exception(close_error)[:500])

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)
        runtime = load_runtime_config()
        capability_status = format_capability_status()
        context_status = format_prompt_system_context()

        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y - %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders. "
            f"If user says 'in 2 minutes', add 2 minutes to this time.\n\n"
        )

        recovery_ctx = ""
        if self._disconnect_count > 0:
            recovery_ctx = (
                "[SESSION RECOVERY]\n"
                "The live connection recently dropped and was re-established.\n"
                "Continue naturally from the recovered archive and any partial turn notes below.\n"
                "Do not act like the conversation context was lost.\n\n"
            )

        prompt_prefix = time_ctx + context_status + "\n\n" + recovery_ctx
        if mem_str:
            sys_prompt = prompt_prefix + mem_str + "\n\n" + capability_status + "\n\n" + sys_prompt
        else:
            sys_prompt = prompt_prefix + capability_status + "\n\n" + sys_prompt

        self.live_model = runtime.get("live_model") or DEFAULT_LIVE_MODEL
        voice_name = runtime.get("voice_name") or "Charon"
        session_resumption = types.SessionResumptionConfig()
        if self._session_resumption_handle:
            session_resumption.handle = self._session_resumption_handle

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=sys_prompt,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=session_resumption,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[AXIOM] TOOL: {name}  ARGS: {args}")

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Opened {args.get('app_name')} successfully."

            elif name == "weather_report":
                r = await loop.run_in_executor(
                    None, lambda: weather_action(parameters=args, player=self.ui)
                )
                result = r or f"Weather report for {args.get('city')} delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(parameters=args, player=self.ui)
                )
                result = r or "Browser action completed."

            elif name == "file_controller":
                r = await loop.run_in_executor(
                    None, lambda: file_controller(parameters=args, player=self.ui)
                )
                result = r or "File operation completed."

            elif name == "send_message":
                r = await loop.run_in_executor(
                    None, lambda: send_message(
                        parameters=args, response=None,
                        player=self.ui, session_memory=None
                    )
                )
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(
                    None, lambda: reminder(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Reminder set for {args.get('date')} at {args.get('time')}."

            elif name == "youtube_video":
                r = await loop.run_in_executor(
                    None, lambda: youtube_video(parameters=args, response=None, player=self.ui)
                )
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = (
                    "Vision module activated. "
                    "Stay completely silent - vision module will speak directly."
                )

            elif name == "computer_settings":
                r = await loop.run_in_executor(
                    None, lambda: computer_settings(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or "Done."

            elif name == "cmd_control":
                r = await loop.run_in_executor(
                    None, lambda: cmd_control(parameters=args, player=self.ui)
                )
                result = r or "Command executed."

            elif name == "desktop_control":
                r = await loop.run_in_executor(
                    None, lambda: desktop_control(parameters=args, player=self.ui)
                )
                result = r or "Desktop action completed."
            elif name == "code_helper":
                r = await loop.run_in_executor(
                    None, lambda: code_helper(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "codex_builder":
                r = await loop.run_in_executor(
                    None, lambda: codex_builder(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(
                    None, lambda: dev_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."
            elif name == "agent_task":
                goal         = args.get("goal", "")
                priority_str = args.get("priority", "normal").lower()

                from agent.task_queue import get_queue, TaskPriority
                priority_map = {
                    "low":    TaskPriority.LOW,
                    "normal": TaskPriority.NORMAL,
                    "high":   TaskPriority.HIGH,
                }
                priority = priority_map.get(priority_str, TaskPriority.NORMAL)

                queue   = get_queue()
                task_id = queue.submit(
                    goal=goal,
                    priority=priority,
                    speak=self.speak,
                )
                result = f"Task started (ID: {task_id}). I'll update you as I make progress."

            elif name == "web_search":
                r = await loop.run_in_executor(
                    None, lambda: web_search_action(parameters=args, player=self.ui)
                    )
                result = r or "Search completed."
            elif name == "computer_control":
                r = await loop.run_in_executor(
                    None, lambda: computer_control(parameters=args, player=self.ui)
                )
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(
                    None, lambda: flight_finder(parameters=args, player=self.ui)
                )
                result = r or "Done."
                
            elif name in ("memory_archive", "nexus_memory"):
                r = await loop.run_in_executor(
                    None, lambda: memory_archive(parameters=args, player=self.ui)
                )
                result = r or "Done."

            elif name == "deep_analyzer":
                r = await loop.run_in_executor(
                    None, lambda: deep_analyzer(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "autonomous_researcher":
                r = await loop.run_in_executor(
                    None, lambda: autonomous_research(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "mt5_trading":
                r = await loop.run_in_executor(
                    None, lambda: mt5_trading(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "predict_market":
                r = await loop.run_in_executor(
                    None, lambda: predict_market(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "mirofish_control":
                r = await loop.run_in_executor(
                    None, lambda: mirofish_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "tradingagents_control":
                r = await loop.run_in_executor(
                    None, lambda: tradingagents_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "self_modifier":
                r = await loop.run_in_executor(
                    None, lambda: self_modifier(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "skill_library":
                r = await loop.run_in_executor(
                    None, lambda: skill_library(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "agent_library":
                r = await loop.run_in_executor(
                    None, lambda: agent_library(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "system_capabilities":
                r = await loop.run_in_executor(
                    None, lambda: system_capabilities(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "deerflow_control":
                r = await loop.run_in_executor(
                    None, lambda: deerflow_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "automaton_control":
                r = await loop.run_in_executor(
                    None, lambda: automaton_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "dexter_control":
                r = await loop.run_in_executor(
                    None, lambda: dexter_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "pentagi_control":
                r = await loop.run_in_executor(
                    None, lambda: pentagi_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "lightpanda_control":
                r = await loop.run_in_executor(
                    None, lambda: lightpanda_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "autoresearch_control":
                r = await loop.run_in_executor(
                    None, lambda: autoresearch_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "persona_control":
                r = await loop.run_in_executor(
                    None, lambda: persona_control(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "prompt_studio":
                r = await loop.run_in_executor(
                    None, lambda: prompt_studio(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "lead_researcher":
                r = await loop.run_in_executor(
                    None, lambda: lead_researcher(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "swarm_orchestrator":
                r = await loop.run_in_executor(
                    None, lambda: swarm_orchestrator(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            else:
                dynamic_tool = get_dynamic_tool(name)
                if dynamic_tool is not None:
                    r = await loop.run_in_executor(
                        None, lambda: dynamic_tool(
                            parameters=args,
                            player=self.ui,
                            speak=self.speak
                        )
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()

        print(f"[AXIOM] RESULT {name} -> {result[:80]}")

        return types.FunctionResponse(
            id=fc.id,
            name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[AXIOM] Mic started")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        try:
            while True:
                data = await asyncio.to_thread(
                    stream.read, CHUNK_SIZE, exception_on_overflow=False
                )
                
                try:
                    raw_audio = np.frombuffer(data, dtype=np.int16)
                    rms = np.sqrt(np.mean(np.square(raw_audio.astype(np.float32))))
                    gain = self._adaptive_gain(rms)
                    boosted_audio = np.clip(
                        raw_audio.astype(np.float32) * gain,
                        -32768,
                        32767,
                    ).astype(np.int16)
                    boosted_data = boosted_audio.tobytes()
                    interrupt_threshold = self._interrupt_threshold()

                    if not self.is_speaking and rms < (interrupt_threshold * 0.8):
                        self._ambient_rms = (self._ambient_rms * 0.92) + (max(rms, 50.0) * 0.08)
                    
                    if self.is_speaking:
                        if rms > interrupt_threshold:
                            print(f"[AXIOM] Interrupted by user (RMS: {rms:.0f}, threshold: {interrupt_threshold:.0f})")
                            while not self.audio_in_queue.empty():
                                try: self.audio_in_queue.get_nowait()
                                except: break
                            self.is_speaking = False
                            self._speaker_guard_until = time.time() + 0.10
                            data = boosted_data
                        else:
                            data = b'\x00' * len(data)
                    else:
                        if time.time() < self._speaker_guard_until and rms < self._speaker_guard_threshold():
                            data = b'\x00' * len(data)
                        else:
                            data = boosted_data
                        
                except Exception as e:
                    pass
                    
                await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
        except Exception as e:
            print(f"[AXIOM] Mic error: {e}")
            raise
        finally:
            stream.close()

    async def _receive_audio(self):
        print("[AXIOM] Receive loop started")
        try:
            while True:
                turn = self.session.receive()
                async for response in turn:
                    if response.session_resumption_update:
                        self._note_session_resumption_update(response.session_resumption_update)

                    if response.go_away:
                        await self._handle_go_away(response.go_away)
                        continue

                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                self._input_turn_buffer.append(txt)

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                self._output_turn_buffer.append(txt)

                        if sc.turn_complete:
                            self._finalize_transcript_turn()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[AXIOM] Tool call: {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            self._recover_partial_transcript(str(e) or "Connection dropped while a turn was in progress.")
            print(f"[AXIOM] Receive error: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[AXIOM] Playback started")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                self.is_speaking = True
                await asyncio.to_thread(stream.write, chunk)
                if self.audio_in_queue.empty():
                    self.is_speaking = False
                    self._speaker_guard_until = time.time() + 0.12
        except Exception as e:
            print(f"[AXIOM] Playback error: {e}")
            raise
        finally:
            self.is_speaking = False
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while not self._shutdown_requested.is_set():
            try:
                reconnecting = self._disconnect_count > 0
                print("[AXIOM] Connecting...")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=self.live_model, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._go_away_requested = False

                    print("[AXIOM] Connected.")
                    if reconnecting:
                        self.ui.write_log("SYS: Live link restored. Recent context was reloaded.")
                        log_event(
                            "session",
                            "reconnected",
                            self._last_disconnect_reason[:500],
                            metadata={"used_resumption_handle": bool(self._session_resumption_handle)},
                        )
                    else:
                        self.ui.write_log("AXIOM online.")
                        log_event("session", "connected", "Live session established.")
                    self._last_disconnect_reason = ""

                    heartbeat = HeartbeatDaemon(speak_func=self.speak, log_func=self.ui.write_log)
                    tg.create_task(heartbeat.start())

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                if self._shutdown_requested.is_set():
                    break
                self._disconnect_count += 1
                self._last_disconnect_reason = _summarize_exception(e)
                planned_rotation = self._go_away_requested and _is_clean_rotation_error(e)
                invalid_resumption = _is_invalid_resumption_error(e)
                if invalid_resumption and self._session_resumption_handle:
                    stale_handle = self._session_resumption_handle
                    self._session_resumption_handle = ""
                    self._session_resumable = False
                    log_event(
                        "session",
                        "resumption_handle_cleared",
                        stale_handle[:48],
                        metadata={"reason": self._last_disconnect_reason[:220]},
                    )
                log_event(
                    "session",
                    "rotation_reconnect" if planned_rotation else "connection_error",
                    self._last_disconnect_reason[:500],
                    metadata={
                        "disconnect_count": self._disconnect_count,
                        "has_resumption_handle": bool(self._session_resumption_handle),
                        "go_away_requested": self._go_away_requested,
                        "invalid_resumption": invalid_resumption,
                    },
                )
                if planned_rotation:
                    self.ui.write_log("SYS: Live session rotated. Reconnecting with recovered context.")
                    print(f"[AXIOM] Planned live-session rotation: {e}")
                else:
                    self.ui.write_log("SYS: Live link dropped. Reconnecting in 3s with context recovery.")
                    print(f"[AXIOM] Error: {e}")
                    traceback.print_exc()
            finally:
                self.session = None
                self._loop = None
                self.audio_in_queue = None
                self.out_queue = None

            if self._shutdown_requested.is_set():
                break
            delay_seconds = 0.5 if self._go_away_requested else 3
            print(f"[AXIOM] Reconnecting in {delay_seconds}s...")
            await asyncio.sleep(delay_seconds)

def main():
    init_runtime_store()
    face_path = BASE_DIR / "assets" / "face.png"
    ui = AxiomUI(str(face_path) if face_path.exists() else "")
    runner_state = {"thread": None, "axiom": None, "cleanup_started": False}

    def shutdown_runtime():
        if runner_state["cleanup_started"]:
            return
        runner_state["cleanup_started"] = True

        axiom = runner_state.get("axiom")
        if axiom is not None:
            try:
                axiom.request_shutdown()
            except Exception:
                pass

        try:
            stop_telegram_bridge(timeout=2.5)
        except Exception:
            pass

        try:
            shutdown_browser_control(timeout=10)
        except Exception:
            pass

        thread = runner_state.get("thread")
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)

        try:
            pya.terminate()
        except Exception:
            pass

    ui.set_close_handler(shutdown_runtime)
    atexit.register(shutdown_runtime)

    def runner():
        ui.wait_for_api_key()
        start_telegram_bridge(log_func=ui.write_log)
        boot_integrations(log_func=ui.write_log)
        for line in boot_doctor_lines(limit=6):
            ui.write_log(f"SYS: {line}")
            log_event("doctor", "boot", line[:2000])

        axiom = AxiomLive(ui)
        runner_state["axiom"] = axiom
        try:
            asyncio.run(axiom.run())
        except KeyboardInterrupt:
            print("\n[AXIOM] Shutting down...")
        finally:
            runner_state["axiom"] = None

    runner_state["thread"] = threading.Thread(target=runner, daemon=True, name="AxiomRuntime")
    runner_state["thread"].start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
