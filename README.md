# A.X.I.O.M v4.3
### Live Voice Operator, Autonomous Execution, Research, Memory, and Channel Control

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
- Archived conversation turns with searchable cross-session recall.
- Live system context awareness for timezone, locale, and best-effort location.
- MT5 trading with stop-loss / take-profit defaults and post-trade reflection.
- Hardware RGB control through OpenRGB.
- Prompt generation, public lead research, and generalized swarm reasoning.
- Optional PersonaPlex sidecar integration for personality/voice experiments.
- Optional Telegram bridge for remote chat, task queuing, and status checks.

This repo keeps the core runtime local and stable. Larger external systems such as PersonaPlex, MiroFish, and Automaton are treated as optional integrations instead of being left as broken placeholder submodules.

---

## Architecture

<p align="center">
  <img src="assets/architecture-overview.svg" alt="AXIOM architecture overview" width="100%">
</p>

This is the actual shape of the project now: a Gemini Live runtime at the center, an action/tool layer for execution, a separate task engine for longer jobs, and a persistent memory/state layer underneath it.

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
| Runtime Awareness | Inspect installed integrations, recent events, failures, timezone, and system context |
| Task Persistence | Record task queue lifecycle checkpoints for later inspection |
| Memory Recall | Search old nexus knowledge and archived conversation turns |
| Persona | Manage optional PersonaPlex configuration and launch instructions |
| Channels | Optional Telegram bot bridge for remote chat and task submission |

---

## Languages Used

| Layer | Languages / Formats |
|------|----------------------|
| Core runtime | Python |
| Desktop launch | Batch (`Axiom.bat`) |
| External agent runtime | TypeScript / Node.js (`automaton_upstream`) |
| Config | JSON |
| Durable state | SQLite / SQL |
| Diagrams | SVG + Mermaid |
| Shell examples | PowerShell / Bash |

AXIOM itself is Python-first. The current "one brain" model coordinates Python-native tools plus optional external runtimes such as MiroFish and Conway Automaton.

---

## Repo Layout

```text
main.py                          Live Gemini runtime and tool dispatcher
ui.py                            Desktop HUD and first-run secret setup
actions/                         Tool modules, including mirofish_control and automaton_control
agent/                           Planner, executor, queue, heartbeat
core/                            Prompt, runtime config, capability detection, integration bridges
memory/                          Long-term memory, runtime SQLite store, trading soul
config/runtime.json              Public non-secret runtime defaults
config/runtime.local.json        Optional local override file (ignored by git)
config/api_keys.example.json     Public example secret file
core/integration_manager.py      Boot-time orchestration for external integrations
core/mirofish_bridge.py          MiroFish detection, status, context, startup bridge
core/automaton_bridge.py         Automaton detection, status, memory snapshot, startup bridge
```

---

## Unified Boot Flow

```mermaid
flowchart TD
    A[User runs axiom or Axiom.bat] --> B[main.py]
    B --> C[Desktop UI loads]
    C --> D[Secrets checked from config/api_keys.json or env]
    D --> E[Telegram bridge start attempt]
    E --> F[boot_integrations()]
    F --> G[MiroFish auto-start if configured]
    F --> H[Automaton auto-start if configured]
    G --> I[Axiom Live runtime]
    H --> I
    I --> J[Planner / Executor / Action layer]
    J --> K[Memory archive + Nexus index + runtime SQLite store]
```

The entrypoint is intentionally single-root now: start AXIOM once, then let AXIOM decide which local sidecars it can safely bring online.

---

## Startup and Memory Flow

<p align="center">
  <img src="assets/startup-memory-flow.svg" alt="AXIOM startup and memory flow" width="100%">
</p>

The important change here is that Axiom no longer relies only on shallow prompt memory. It now archives conversation turns, keeps structured long-term memory, and can search that history again later.

---

## Live Runtime Recovery

<p align="center">
  <img src="assets/live-runtime-resilience.svg" alt="AXIOM live runtime resilience" width="100%">
</p>

The live runtime now does three extra things:

- Uses adaptive input gain and stricter speaker-echo guards so softer or accented speech is easier to catch without letting Axiom talk to itself.
- Replies conversationally over Telegram for normal chat instead of queueing everything like a batch task.
- Preserves partial transcript state through reconnects and reloads recent context when the live session comes back.

---

## Quick Start

```bash
git clone https://github.com/moyesrex-ops/Axiom.git
cd Axiom
pip install -r requirements.txt
python -m playwright install chromium
copy config\api_keys.example.json config\api_keys.json
Axiom.bat
```

If `axiom` is already on your `PATH`, you can launch with:

```powershell
axiom
```

If not, `Axiom.bat` remains the canonical Windows launcher.

The public repo now ships an example file:

```json
{
  "gemini_api_key": "",
  "telegram_bot_token": "",
  "camera_index": 0
}
```

Copy it to `config/api_keys.json` and fill only the secrets you actually want locally, or let the UI create that file on first run.

`config/api_keys.json` is intentionally ignored by git and should never contain real secrets in a public push.

For machine-specific integration paths or auto-start preferences, create `config/runtime.local.json`. AXIOM merges that file on top of the tracked `config/runtime.json`.
When `config/runtime.local.json` exists, AXIOM now writes future runtime updates there by default so tracked `config/runtime.json` can stay clean.

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
      "queue_plain_messages": true,
      "startup_prompt_enabled": true
    }
  },
  "integrations": {
    "mirofish_path": "",
    "mirofish_url": "http://127.0.0.1:5001",
    "mirofish_auto_start": false,
    "automaton_path": "",
    "automaton_state_dir": "",
    "automaton_auto_start": false,
    "personaplex_path": ""
  },
  "browser": {
    "backend": "playwright",
    "lightpanda_endpoint": "http://127.0.0.1:9222",
    "lightpanda_auto_connect": false,
    "lightpanda_repo_path": "",
    "lightpanda_wsl_binary_path": ""
  },
  "skill_library": {
    "enabled": true,
    "everything_claude_code_path": "",
    "superpowers_path": "",
    "antigravity_skills_path": "",
    "search_limit": 8
  },
  "research_repos": {
    "autoresearch_path": ""
  },
  "system_context": {
    "enable_public_ip_lookup": false
  }
}
```

This keeps voice/model/integration settings out of the source code.

`config/runtime.local.json` is optional and ignored by git. Use it for local absolute paths like:

```json
{
  "integrations": {
    "mirofish_path": "C:\\Users\\you\\MiroFish",
    "mirofish_auto_start": true,
    "automaton_path": "C:\\Users\\you\\automaton_upstream",
    "automaton_state_dir": "C:\\Users\\you\\.automaton",
    "automaton_auto_start": true
  },
  "browser": {
    "lightpanda_endpoint": "http://127.0.0.1:9222",
    "lightpanda_repo_path": "C:\\Users\\you\\Axiom_research\\external\\lightpanda-browser",
    "lightpanda_wsl_binary_path": "/home/you/.local/bin/lightpanda"
  },
  "research_repos": {
    "autoresearch_path": "C:\\Users\\you\\Axiom_research\\external\\autoresearch"
  }
}
```

Startup behavior:

- If Gemini is not configured, the first-run setup panel asks for the Gemini key and offers optional Telegram linking.
- If Gemini is configured but Telegram is not, Axiom can show a separate optional Telegram link prompt at startup.
- Telegram remains optional. Skip it and Axiom continues to run locally.
- System context is inferred at runtime and injected into the live prompt, so reminders and time-sensitive responses use the local machine context by default.
- Public IP geolocation is opt-in through `system_context.enable_public_ip_lookup`. The default path stays local-first and relies on timezone/locale hints only.

---

## New Integrated Tools

### `system_capabilities`
Inspect the live environment, installed integrations, recent runtime events, recent failures, recent task checkpoints, and live system context.

### `skill_library`
Search and read integrated external skill libraries from:

- Everything Claude Code
- Superpowers
- Antigravity Awesome Skills

This gives AXIOM a searchable library of workflows, testing patterns, debugging playbooks, and implementation guidance.

### `nexus_memory`
The memory tool now supports:

- `save`
- `recall`
- `list`
- `recent`
- `search`

That means Axiom can search both saved nexus topics and archived conversation turns instead of relying only on the latest saved note.

### `persona_control`
Configure optional PersonaPlex integration, inspect its status, or get launch instructions.

### `lightpanda_control`
Inspect, configure, or start the optional Lightpanda CDP backend. AXIOM can now detect a WSL-installed Lightpanda binary, resolve the usable websocket endpoint, and report whether the backend is actually reachable from Windows.

### `autoresearch_control`
Inspect the local `autoresearch` repo, read `program.md`, prepare the dataset/tokenizer, run a real training baseline, inspect `results.tsv`, and check whether the experiment loop is ready to run.

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

Plain chat messages get a conversational reply.
If `queue_plain_messages` is enabled, operational plain messages can auto-execute as tasks only for explicitly allowed chat IDs. If the allowed list is empty, chat replies still work but execution is locked.

At startup, Telegram linking is optional. If you do not provide a bot token, Axiom stays local-only and the rest of the runtime still works.

### MiroFish / Automaton

AXIOM now has real bridge modules for both systems instead of only path detection:

- `mirofish_control` + `core/mirofish_bridge.py`
- `automaton_control` + `core/automaton_bridge.py`
- `core/integration_manager.py` to boot them automatically when enabled

What that means:

- MiroFish can be discovered, queried for local projects/simulations/reports, used as extra market context, and auto-started at AXIOM boot when the local backend is configured correctly.
- Automaton can be discovered, inspected, built-status checked, memory-state inspected, and launch-attempted from AXIOM. It still requires its own first-run config and Conway credentials before it becomes a fully live sub-runtime.

If you want Axiom to know where they live, set:

- `integrations.mirofish_path`
- `integrations.automaton_path`
- `integrations.automaton_state_dir`

If you want AXIOM to auto-start them on boot, also set:

- `integrations.mirofish_auto_start`
- `integrations.automaton_auto_start`

in `config/runtime.json`.

Important Windows note:

- The local MiroFish integration was validated with a writable external log directory override (`MIROFISH_LOG_DIR`) so AXIOM can launch it without colliding with repo-local log files.
- The local Automaton integration was validated through Node 20 + `pnpm build`, but it still needs `automaton --setup` / `--provision` before AXIOM can bring it fully online.

### Lightpanda

AXIOM now understands an optional Lightpanda browser backend:

- `lightpanda_control` inspects repo state, CDP endpoint readiness, start status, and launch instructions.
- `lightpanda_control start` can launch a WSL-installed Lightpanda binary and verify the Windows-visible CDP endpoint.
- `browser.lightpanda_wsl_binary_path` can be set in `runtime.local.json` when WSL discovery is unreliable or you want AXIOM to use a fixed known binary path.
- `browser_control` can connect to Lightpanda over CDP when `browser.backend` is set to `lightpanda` or `lightpanda_auto_connect` is enabled and the endpoint is reachable.
- The safe default remains `browser.backend = "playwright"` so existing browser behavior does not change unless you opt in.
- On current Windows setups, Lightpanda is best treated as an optional beta backend. AXIOM now prefers the stable local browser path by default and can fall back to it if a Lightpanda navigation target collapses.

### External Skill Libraries

AXIOM can now index and search external skill repos if they are cloned locally:

- `everything-claude-code`
- `superpowers`
- `antigravity-awesome-skills`

Point the runtime config at those repos through `skill_library.*_path` fields, or let AXIOM auto-detect them under `C:\Users\<you>\Axiom_research\external\`.

### Autoresearch

AXIOM now has a bridge for Karpathy's `autoresearch` repo:

- It checks whether `uv` is installed.
- It checks whether an NVIDIA GPU is visible.
- It inspects `~/.cache/autoresearch/` for data shards and tokenizer artifacts.
- It can run `prepare.py`, train a real baseline, and parse `results.tsv` afterward.
- The local Windows/RTX validation path now uses a low-VRAM fallback profile and writes `results.tsv` rows so AXIOM can inspect real experiment outcomes.

That means AXIOM can report real readiness for autonomous ML experiments instead of just knowing the repo exists.

Verification:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## Notes

- `Axiom.bat` launches the repo directory it lives in and is the intended Windows entrypoint.
- If your environment already provides an `axiom` wrapper or alias, it can point straight to `Axiom.bat`.
- `memory/axiom_state.db` is created at runtime and ignored by git.
- `config/api_keys.json` and long-term memory files are ignored by git.
- `config/api_keys.example.json` is the tracked template for public pushes.
- `config/runtime.local.json` is the intended place for machine-specific path overrides and local boot preferences.
- Telegram is disabled in the public runtime config by default; enable it only after adding a local bot token and explicit allowed chat IDs.
- This repo is designed around Windows first. Some tools are cross-platform, but the main UX targets Windows 10/11.

---

## License

MIT

---

<p align="center">
  <b>A.X.I.O.M</b> - autonomy through execution
</p>
