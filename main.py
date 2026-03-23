import asyncio
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
from memory.memory_manager import load_memory, update_memory, format_memory_for_prompt

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
from actions.browser_control  import browser_control
from actions.file_controller  import file_controller
from actions.code_helper      import code_helper
from actions.dev_agent        import dev_agent
from actions.web_search       import web_search as web_search_action
from actions.computer_control import computer_control
from actions.nexus_memory     import nexus_memory
from actions.deep_analyzer    import deep_analyzer
from actions.autonomous_researcher import autonomous_research
from actions.mt5_trading_agent     import mt5_trading
from actions.market_predictor      import predict_market
from actions.self_modifier         import self_modifier
from agent.heartbeat               import HeartbeatDaemon

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
FORMAT              = pyaudio.paInt16
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

pya = pyaudio.PyAudio()

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are AXIOM, an advanced AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_memory_turn_counter  = 0
_memory_turn_lock     = threading.Lock()
_MEMORY_EVERY_N_TURNS = 5
_last_memory_input    = ""


def _update_memory_async(user_text: str, axiom_text: str) -> None:
    global _memory_turn_counter, _last_memory_input

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
            print(f"[Memory] ✅ Updated: {list(data.keys())}")

    except json.JSONDecodeError:
        pass
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
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
    "description": "Searches the web for any information. Use mode='deep' for Perplexity-style iterative multi-source research. Use mode='social' with query=URL to analyze a Reddit/Twitter/X page and extract strategies.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query":   {"type": "STRING", "description": "Search query or URL (for social mode)"},
            "mode":    {"type": "STRING", "description": "search (default) | compare | deep | social"},
            "items":   {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
            "aspect":  {"type": "STRING", "description": "price | specs | reviews"},
            "context": {"type": "STRING", "description": "What to extract/analyze (for social mode)"}
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
        "Controls YouTube. Use for: playing videos, summarizing a video's content, "
        "getting video info, or showing trending videos."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "play | summarize | get_info | trending (default: play)"
            },
            "query":  {"type": "STRING", "description": "Search query for play action"},
            "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
            "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
            "url":    {"type": "STRING", "description": "Video URL for get_info action"},
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
        "ALSO controls physical RGB hardware lighting (keyboard/mouse color) — use action: change_hardware_color with value: red/blue/green/glowing/off etc. "
        "ALSO use for repeated actions: 'refresh 10 times', 'reload page 5 times' → action: reload_n, value: 10. "
        "ALSO use for safely force-closing a specific app/process by name WITHOUT crashing Axiom — "
        "use action: force_close, value: <process_name> (e.g. value: chrome). "
        "Use for ANY single computer control command — even if repeated N times. "
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
            "booking flights, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
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
        "Writes, edits, explains, runs, or self-builds code files. "
        "Use for ANY coding request: writing a script, fixing a file, "
        "editing existing code, running a file, or building and testing automatically."
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
    "name": "dev_agent",
    "description": (
        "Builds complete multi-file projects from scratch. "
        "Plans structure, writes all files, installs dependencies, "
        "opens VSCode, runs the project, and fixes errors automatically. "
        "Use for any project larger than a single script."
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
        "minimize, screenshot, restart, shutdown — use computer_settings for those. "
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
    "name": "nexus_memory",
    "description": (
        "Saves, recalls, or lists long-term knowledge from the Nexus Brain. "
        "Use this to permanently memorize learned skills, preferences, strategies, "
        "or code snippets so you never forget them. Before attempting complex tasks, "
        "you can use this to recall how you were told to do them previously."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":  {"type": "STRING", "description": "save | recall | list"},
            "topic":   {"type": "STRING", "description": "Topic name (e.g., 'trading_strategy_A', 'my_code_preferences')"},
            "content": {"type": "STRING", "description": "The detailed content to save (required for save action)"}
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
        "It will automatically save the knowledge to the Nexus Brain without you needing to do it."
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
            "action":       {"type": "STRING", "description": "The action to perform: 'info', 'buy', or 'sell'."},
            "symbol":       {"type": "STRING", "description": "The market symbol to trade (e.g., 'EURUSD'). Default is EURUSD."},
            "volume":       {"type": "NUMBER", "description": "The lot size for the trade (e.g., 0.01). Default is 0.01."},
            "stop_loss":    {"type": "NUMBER", "description": "Stop-loss price level. If omitted, a 50-pip default SL is applied automatically."},
            "take_profit":  {"type": "NUMBER", "description": "Take-profit price level. If omitted, a 50-pip default TP is applied automatically."},
            "prompt":       {"type": "STRING", "description": "Natural language trade intent for AI extraction (e.g. 'buy 0.1 lots EURUSD with SL at 1.0800')."},
        },
        "required": ["action"]
    }
},
{
    "name": "predict_market",
    "description": (
        "Spawns a highly intelligent background swarm to synthesize technical and fundamental data "
        "and predict the future trajectory of ANY market asset (Forex, Crypto, Stocks, Polymarket, Kalshi)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "asset": {"type": "STRING", "description": "The asset to predict (e.g., 'Bitcoin', 'EURUSD')."},
            "context": {"type": "STRING", "description": "Any specific news, timeframes, or biases the user provided."}
        },
        "required": ["asset"]
    }
},
{
    "name": "self_modifier",
    "description": (
        "Axiom's self-modification engine. Allows Axiom to read its own source code, "
        "write new Python action scripts into the actions/ directory, edit existing ones, "
        "or use AI to generate entirely new capabilities on the fly. "
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
}
]

class AxiomLive:

    def __init__(self, ui: AxiomUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        
        # Audio tweaks
        self.is_speaking       = False
        self.VOLUME_MULTIPLIER = 5.0   # Extreme volume boost for soft voices/whispering
        self.VAD_THRESHOLD     = 2000  # Calculated solely on RAW unboosted audio to prevent speaker loop

    def speak(self, text: str):
        """Thread-safe speak — any thread can call this."""
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
         )

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)

        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders. "
            f"If user says 'in 2 minutes', add 2 minutes to this time.\n\n"
        )

        if mem_str:
            sys_prompt = time_ctx + mem_str + "\n\n" + sys_prompt
        else:
            sys_prompt = time_ctx + sys_prompt

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=sys_prompt,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[AXIOM] 🔧 TOOL: {name}  ARGS: {args}")

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
                    "Stay completely silent — vision module will speak directly."
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
                
            elif name == "nexus_memory":
                r = await loop.run_in_executor(
                    None, lambda: nexus_memory(parameters=args, player=self.ui)
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

            elif name == "self_modifier":
                r = await loop.run_in_executor(
                    None, lambda: self_modifier(
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

        print(f"[AXIOM] 📤 {name} → {result[:80]}")

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
        print("[AXIOM] 🎤 Mic started")
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
                    
                    # Whisper Boost (API ONLY)
                    boosted_audio = np.clip(raw_audio * self.VOLUME_MULTIPLIER, -32768, 32767).astype(np.int16)
                    boosted_data  = boosted_audio.tobytes()
                    
                    # Interruption Detection (VAD) on RAW audio to prevent 5x speaker amplification trigger
                    rms = np.sqrt(np.mean(np.square(raw_audio.astype(np.float32))))
                    
                    if self.is_speaking:
                        if rms > self.VAD_THRESHOLD:
                            print(f"[AXIOM] 🛑 Interrupted by user! (RMS: {rms:.0f})")
                            # User spoke louder than the speaker threshold. Clear playback queue.
                            while not self.audio_in_queue.empty():
                                try: self.audio_in_queue.get_nowait()
                                except: break
                            self.is_speaking = False
                            data = boosted_data # Let the user's voice through
                        else:
                            # Axiom is speaking, and the mic is picking up Axiom's own voice from the speakers.
                            # Mute the mic stream going to the API so Axiom doesn't talk to itself.
                            data = b'\x00' * len(data)
                    else:
                        # Axiom is not speaking, let the mic stream flow normally
                        data = boosted_data
                        
                except Exception as e:
                    pass # Fallback to raw data if numpy fails
                    
                await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
        except Exception as e:
            print(f"[AXIOM] ❌ Mic error: {e}")
            raise
        finally:
            stream.close()

    async def _receive_audio(self):
        print("[AXIOM] 👂 Recv started")
        out_buf = []
        in_buf  = []

        try:
            while True:
                turn = self.session.receive()
                async for response in turn:

                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.turn_complete:
                            full_in  = ""
                            full_out = ""

                            if in_buf:
                                full_in = " ".join(in_buf).strip()
                                if full_in:
                                    self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            if out_buf:
                                full_out = " ".join(out_buf).strip()
                                if full_out:
                                    self.ui.write_log(f"Axiom: {full_out}")
                            out_buf = []

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[AXIOM] 📞 Tool call: {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[AXIOM] ❌ Recv error: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[AXIOM] 🔊 Play started")
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
        except Exception as e:
            print(f"[AXIOM] ❌ Play error: {e}")
            raise
        finally:
            self.is_speaking = False
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                print("[AXIOM] 🔌 Connecting...")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[AXIOM] ✅ Connected.")
                    self.ui.write_log("AXIOM online.")

                    heartbeat = HeartbeatDaemon(speak_func=self.speak, log_func=self.ui.write_log)
                    tg.create_task(heartbeat.start())

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                print(f"[AXIOM] ⚠️  Error: {e}")
                traceback.print_exc()

            print("[AXIOM] 🔄 Reconnecting in 3s...")
            await asyncio.sleep(3)

def main():
    ui = AxiomUI("face.png")

    def runner():
        ui.wait_for_api_key()

        axiom = AxiomLive(ui)
        try:
            asyncio.run(axiom.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
