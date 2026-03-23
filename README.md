# A.X.I.O.M v4.2
### Live Voice Operator, Autonomous Execution, Research, and Swarm Reasoning

<p align="center">
  <img src="assets/banner.png" alt="AXIOM Banner" width="100%">
</p>

<p align="center">
  <b>Windows-first autonomous operator built around Gemini Live.</b><br>
  Voice I/O · Agent Tasks · Browser + Vision + Desktop Control · Prompt Studio · Public Lead Research
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Gemini-Live%20API-purple?style=flat-square&logo=google&logoColor=white" alt="Gemini">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-black?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
</p>

---

## What This Repo Is

Axiom is no longer just a trading shell. The current repo combines:

- A real-time Gemini Live voice loop for spoken interaction.
- A planner/executor queue for multi-step autonomous tasks.
- Browser, screen, desktop, file, and terminal control.
- Long-term memory plus a durable runtime event/failure store.
- Task lifecycle checkpoints persisted to SQLite.
- MT5 trading with stop-loss / take-profit defaults and post-trade reflection.
- Hardware RGB control through OpenRGB.
- Prompt generation, public lead research, and generalized swarm reasoning.
- Optional PersonaPlex sidecar integration for personality/voice experiments.
- Optional Telegram bridge for remote task queuing and status checks.

This repo keeps the core runtime local and stable. Larger external systems such as PersonaPlex, MiroFish, and Automaton are treated as optional integrations instead of being left as broken placeholder submodules.

---

## Current Capability Set

| Area | What Axiom Can Do |
|------|--------------------|
| Voice | Real-time Gemini Live conversation with configurable runtime voice |
| Agent Tasks | Break down and execute multi-step tasks through the task queue |
| Browser | Search, navigate, click, type, scrape, and automate pages |
| Vision | Analyze the screen or webcam |
| Computer Control | Keyboard, mouse, windows, tabs, scrolling, screenshots |
| Terminal | Generate and run shell commands with safer visible-mode behavior |
| Files | Read, write, search, organize, and inspect files |
| Hardware | Change RGB hardware colors/effects and inspect OpenRGB device status |
| Trading | Execute MT5 orders with SL/TP and closed-trade reflection |
| Research | Deep search, public lead extraction, YouTube/channel research |
| Prompting | Generate image/video prompts with Prompt Studio |
| Swarm | Run generalized multi-role debates for research, strategy, build planning, or critique |
| Runtime Awareness | Inspect installed integrations, recent events, and failures |
| Task Persistence | Record task queue lifecycle checkpoints for later inspection |
| Persona | Manage optional PersonaPlex configuration and launch instructions |
| Channels | Optional Telegram bot bridge for remote task submission |

---

## Repo Layout

```text
main.py                  Live Gemini runtime and tool dispatcher
ui.py                    Desktop HUD
actions/                 Tool modules
agent/                   Planner, executor, queue, heartbeat
core/                    Prompt, runtime config, capability detection, PersonaPlex bridge
memory/                  Long-term memory, runtime SQLite store, trading soul
config/runtime.json      Non-secret runtime settings
config/api_keys.json     Local API keys (created at runtime, ignored by git)
```

---

## Quick Start

```bash
git clone https://github.com/moyesrex-ops/Axiom.git
cd Axiom
pip install -r requirements.txt
python -m playwright install chromium
Axiom.bat
```

On first launch, the UI will ask for your Gemini API key and write:

```json
{
  "gemini_api_key": "YOUR_KEY"
}
```

to `config/api_keys.json`.

You can also create that file manually if you prefer.

---

## Runtime Config

The repo now uses `config/runtime.json` for non-secret runtime behavior. Important fields:

```json
{
  "voice_name": "Charon",
  "voice_backend": "gemini_live",
  "live_model": "models/gemini-2.5-flash-native-audio-preview-12-2025",
  "personaplex": {
    "enabled": false,
    "server_url": "ws://127.0.0.1:8998/api/chat",
    "repo_path": "",
    "cpu_offload": false
  },
  "channels": {
    "telegram": {
      "enabled": false,
      "allowed_chat_ids": [],
      "poll_seconds": 1.5,
      "queue_plain_messages": true
    }
  },
  "integrations": {
    "mirofish_path": "",
    "automaton_path": "",
    "personaplex_path": ""
  }
}
```

This keeps voice/model/integration settings out of the source code.

---

## New Integrated Tools

### `system_capabilities`
Inspect the live environment, installed integrations, recent runtime events, recent failures, and recent task checkpoints.

### `persona_control`
Configure optional PersonaPlex integration, inspect its status, or get launch instructions.

### `prompt_studio`
Generate strong image/video prompts, variations, and negative prompts.

### `lead_researcher`
Extract public business lead signals such as emails, phones, and social links from public pages.

### `swarm_orchestrator`
Run generalized multi-role debates for research, strategy, build planning, or critique.

---

## Optional Integrations

### OpenRGB

Hardware RGB control depends on:

- `openrgb-python` installed
- OpenRGB desktop app running
- OpenRGB SDK server reachable on the local machine

Once that is active, Axiom can change colors/effects and inspect connected RGB devices.

### MetaTrader 5

Trading depends on:

- MetaTrader 5 desktop installed and logged in
- Python `MetaTrader5` package available

The repo now applies default SL/TP values when the user does not provide them and monitors closed positions to reflect on trade outcomes.

### PersonaPlex

PersonaPlex is integrated as an optional sidecar, not as a forced replacement for the Gemini Live loop.

High-level flow:

1. Clone `NVIDIA/personaplex` somewhere local.
2. Accept the model license on Hugging Face.
3. Set `HF_TOKEN`.
4. Point `config/runtime.json` `personaplex.repo_path` to that clone, or let Axiom detect it.
5. Use `persona_control` to inspect/configure it.
6. Launch the PersonaPlex server when needed.

The built-in launch pattern is:

```powershell
Set-Location 'C:\path\to\personaplex'
$ssl = Join-Path $env:TEMP 'personaplex-ssl'
New-Item -ItemType Directory -Force $ssl | Out-Null
python -m moshi.server --ssl $ssl
```

If GPU memory is tight, enable `cpu_offload` in `config/runtime.json`.

### Telegram Bridge

Axiom can optionally expose a lightweight Telegram bot bridge inspired by DeerFlow's IM channel pattern.

Setup:

1. Create a bot with [@BotFather](https://t.me/BotFather).
2. Add `telegram_bot_token` to `config/api_keys.json`, or set `AXIOM_TELEGRAM_BOT_TOKEN`.
3. Enable `channels.telegram.enabled` in `config/runtime.json`.
4. Optionally add your Telegram chat ID(s) to `channels.telegram.allowed_chat_ids`.

Supported commands:

- `/status`
- `/tasks`
- `/task <goal>`

If `queue_plain_messages` is enabled, ordinary messages are also queued as tasks.

### MiroFish / Automaton

These are treated as external optional repos now. The runtime can detect local clones and expose their presence through `system_capabilities`, but they are not left in this repo as dead gitlinks anymore.

If you want Axiom to know where they live, set:

- `integrations.mirofish_path`
- `integrations.automaton_path`

in `config/runtime.json`.

---

## Notes

- `Axiom.bat` now launches the repo directory it lives in.
- `memory/axiom_state.db` is created at runtime and ignored by git.
- `config/api_keys.json` and long-term memory files are ignored by git.
- This repo is designed around Windows first. Some tools are cross-platform, but the main UX targets Windows 10/11.

---

## License

MIT

---

<p align="center">
  <b>A.X.I.O.M</b> - autonomy through execution
</p>
