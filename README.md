# A.X.I.O.M
### Autonomous eXecution & Intelligent Operations Module

<p align="center">
  <img src="assets/banner.png" alt="AXIOM Banner" width="100%">
</p>

<p align="center">
  <b>A voice-driven AI assistant powered by the Gemini Live API</b><br>
  Real-time audio · Screen analysis · Browser automation · 16+ tool capabilities
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Gemini-Live%20API-purple?style=flat-square&logo=google&logoColor=white" alt="Gemini">
  <img src="https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
</p>

---

## 🚀 What is Axiom?

Axiom is a personal AI assistant that listens to your voice in real-time and executes tasks on your computer. It combines **Gemini's Live Audio API** for natural conversation with **16 specialized tool modules** for everything from web search to code generation.

Think of it as your own JARVIS — running locally, using only a single Gemini API key.

---

## ✨ Features

| Category | Capabilities |
|----------|-------------|
| 🎙️ **Voice** | Real-time conversation via Gemini Live API with native audio I/O |
| 👁️ **Vision** | Capture and analyze your screen or webcam with Gemini vision |
| 🌐 **Browser** | Full Playwright-based browser automation (navigate, click, type, fill forms) |
| 📁 **Files** | Create, read, write, move, copy, delete, find files and folders |
| 🔍 **Search** | Gemini Search with DuckDuckGo fallback |
| 📱 **Apps** | Open any application by name (cross-platform) |
| 💻 **Code** | Write, edit, run, and explain code in any language |
| 🏗️ **Projects** | Build multi-file projects from scratch with auto-fix |
| 🤖 **Agent** | Plan and execute complex multi-step tasks across tools |
| 🧠 **Memory** | Persistent memory — remembers your name, preferences, and context |
| 🖥️ **Terminal** | Run any system command via natural language |
| ⚙️ **Control** | Volume, brightness, keyboard shortcuts, scrolling, screenshots |
| ⏰ **Reminders** | Set timed reminders via Windows Task Scheduler |
| 📺 **YouTube** | Play, summarize, get video info, trending videos |
| 🌤️ **Weather** | Real-time weather reports |
| ✈️ **Flights** | Search Google Flights for tickets |
| 💬 **Messaging** | Send WhatsApp/Telegram messages |
| 🖼️ **Desktop** | Wallpaper, organize, clean desktop |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│              main.py (Entry Point)           │
│         Gemini Live API Voice Engine         │
├──────────┬──────────────┬───────────────────┤
│  ui.py   │  memory/     │    agent/          │
│  HUD     │  - manager   │  - task_queue      │
│  Window  │  - config    │  - planner         │
│          │              │  - executor        │
│          │              │  - error_handler   │
├──────────┴──────────────┴───────────────────┤
│              actions/ (16 Tool Modules)       │
│  web_search · browser · files · screen       │
│  code · dev_agent · apps · cmd · desktop     │
│  settings · control · reminders · youtube    │
│  weather · messaging · flights               │
└─────────────────────────────────────────────┘
```

---

## 📋 Quick Start

### Prerequisites

- **Python 3.11+**
- **Windows 10/11** (primary platform)
- **Gemini API key** — get one at [aistudio.google.com](https://aistudio.google.com/)
- **Microphone + speakers** for voice interaction

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/Axiom.git
cd Axiom

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
python -m playwright install chromium

# Run Axiom
python main.py
```

On first launch, Axiom will display a setup dialog asking for your **Gemini API key**.

---

## 📁 Project Structure

```
Axiom/
├── main.py                  # Entry point — Gemini Live API voice connection
├── ui.py                    # Tkinter HUD with animated interface
├── setup.py                 # One-click installer
├── requirements.txt         # Python dependencies
├── assets/
│   └── banner.png           # Project banner
├── config/                  # API key storage (gitignored)
├── core/
│   └── prompt.txt           # System prompt
├── memory/
│   ├── memory_manager.py    # Persistent memory system
│   └── config_manager.py    # Config file management
├── agent/
│   ├── task_queue.py        # Priority task queue with concurrency
│   ├── planner.py           # Multi-step task planner (Gemini-powered)
│   ├── executor.py          # Step execution with context injection
│   └── error_handler.py     # Error analysis & smart recovery
└── actions/                 # 16 tool modules
    ├── web_search.py        # Gemini Search + DuckDuckGo fallback
    ├── browser_control.py   # Playwright browser automation
    ├── file_controller.py   # File/folder CRUD operations
    ├── screen_processor.py  # Screen/webcam capture + Gemini vision
    ├── code_helper.py       # Code write, edit, run, explain
    ├── dev_agent.py         # Multi-file project builder
    ├── open_app.py          # Cross-platform app launcher
    ├── cmd_control.py       # Terminal command execution
    ├── computer_settings.py # Volume, brightness, window management
    ├── computer_control.py  # Mouse, keyboard, form automation
    ├── desktop.py           # Desktop wallpaper, organize, clean
    ├── reminder.py          # Windows Task Scheduler reminders
    ├── weather_report.py    # Weather via Gemini search
    ├── send_message.py      # WhatsApp/Telegram messaging
    ├── youtube_video.py     # YouTube search, play, summarize
    └── flight_finder.py     # Google Flights search
```

---

## 🔑 Single API Key

Axiom runs entirely on **one Gemini API key**. No OpenAI, no Anthropic, no external services needed. The same key powers:

- Voice conversation (Gemini Live API)
- Web search (Gemini + Google Search)
- Task planning & error analysis
- Code generation
- Memory updates
- Screen/camera analysis

---

## 🧠 How the Agent System Works

When you give Axiom a complex multi-step task:

1. **Planner** breaks the goal into tool-call steps using Gemini
2. **Executor** runs each step, injecting context between them
3. **Error Handler** analyzes failures and decides: retry, skip, replan, or abort
4. **Task Queue** manages concurrent background tasks with priorities

---

## 📄 License

MIT

---

<p align="center">
  <b>A.X.I.O.M</b> — Built with Gemini
</p>
