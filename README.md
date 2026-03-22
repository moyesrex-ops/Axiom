# A.X.I.O.M
### Autonomous eXecution & Intelligent Operations Module

A voice-driven AI assistant powered by the **Gemini Live API** with real-time audio, screen analysis, browser automation, and 16+ tool capabilities.

---

## Features

- **Real-time Voice** — Natural conversation via Gemini Live API with native audio I/O
- **Screen & Camera Analysis** — Capture and analyze your screen or webcam with Gemini vision
- **Browser Automation** — Full Playwright-based browser control (navigate, click, type, fill forms)
- **File Management** — Create, read, write, move, copy, delete, find files and folders
- **Web Search** — Gemini Search with DuckDuckGo fallback
- **App Launcher** — Open any application by name (cross-platform)
- **Code Helper** — Write, edit, run, and explain code in any language
- **Dev Agent** — Build multi-file projects from scratch with auto-fix
- **Multi-step Agent** — Plan and execute complex tasks across multiple tools
- **Persistent Memory** — Remembers your name, preferences, and personal context
- **Terminal Commands** — Run any system command via natural language
- **Computer Control** — Volume, brightness, keyboard shortcuts, scrolling, screenshots
- **Reminders** — Set timed reminders via Windows Task Scheduler
- **YouTube** — Play, summarize, get video info, trending videos
- **Weather** — Real-time weather reports
- **Flight Search** — Search Google Flights for tickets
- **Messaging** — Send WhatsApp/Telegram messages
- **Desktop Management** — Wallpaper, organize, clean desktop

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browsers
python -m playwright install chromium

# 3. Run Axiom
python main.py
```

On first launch, Axiom will ask for your **Gemini API key**. Get one at [aistudio.google.com](https://aistudio.google.com/).

## Project Structure

```
Axiom/
├── main.py              # Entry point — Gemini Live API voice connection
├── ui.py                # Tkinter HUD with animated interface
├── setup.py             # One-click installer
├── requirements.txt     # Python dependencies
├── config/              # API key storage
├── core/
│   └── prompt.txt       # System prompt
├── memory/
│   ├── memory_manager.py    # Persistent memory system
│   └── config_manager.py    # Config file management
├── agent/
│   ├── task_queue.py    # Priority task queue
│   ├── planner.py       # Multi-step task planner (Gemini)
│   ├── executor.py      # Step execution engine
│   └── error_handler.py # Error analysis & recovery
└── actions/             # 16 tool modules
    ├── web_search.py
    ├── browser_control.py
    ├── file_controller.py
    ├── screen_processor.py
    ├── code_helper.py
    ├── dev_agent.py
    ├── open_app.py
    ├── cmd_control.py
    ├── computer_settings.py
    ├── computer_control.py
    ├── desktop.py
    ├── reminder.py
    ├── weather_report.py
    ├── send_message.py
    ├── youtube_video.py
    └── flight_finder.py
```

## Requirements

- Python 3.11+
- Windows 10/11 (primary), macOS/Linux (partial support)
- Gemini API key
- Microphone and speakers for voice interaction

## License

MIT
