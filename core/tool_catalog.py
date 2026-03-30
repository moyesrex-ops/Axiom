from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    description: str
    aliases: tuple[str, ...] = ()


_CATEGORY_ORDER = (
    "system",
    "orchestration",
    "research",
    "communications",
    "browser_vision",
    "coding",
    "trading",
    "integrations",
)


_TOOL_SPECS: dict[str, ToolSpec] = {
    "system_capabilities": ToolSpec(
        "system_capabilities",
        "system",
        "Live source of truth for runtime status, doctor checks, operator surface, integrations, tasks, and failures.",
        aliases=("system_status", "capabilities"),
    ),
    "memory_archive": ToolSpec(
        "memory_archive",
        "system",
        "Durable memory save, recall, search, and recent-history access.",
        aliases=("memory", "nexus_memory"),
    ),
    "skill_library": ToolSpec(
        "skill_library",
        "orchestration",
        "Read and recommend imported skill workflows from external repos.",
        aliases=("skills",),
    ),
    "agent_library": ToolSpec(
        "agent_library",
        "orchestration",
        "Read and recommend imported agent cards and delegate specialist work when appropriate.",
        aliases=("agents",),
    ),
    "self_modifier": ToolSpec(
        "self_modifier",
        "orchestration",
        "Modify AXIOM's local behavior by reading, writing, editing, or generating actions and changing voice.",
    ),
    "swarm_orchestrator": ToolSpec(
        "swarm_orchestrator",
        "orchestration",
        "Coordinate specialist-style multi-role reasoning for complex tasks.",
    ),
    "web_search": ToolSpec(
        "web_search",
        "research",
        "General current-information retrieval and deep web research.",
    ),
    "gemini_native": ToolSpec(
        "gemini_native",
        "research",
        "Grounded Gemini tools for Search, URL Context, Code Execution, Maps, and File Search.",
    ),
    "deep_analyzer": ToolSpec(
        "deep_analyzer",
        "research",
        "Long-form research and synthesis across sources.",
    ),
    "autonomous_researcher": ToolSpec(
        "autonomous_researcher",
        "research",
        "Autonomous multi-step research runner for a focused topic.",
    ),
    "deerflow_control": ToolSpec(
        "deerflow_control",
        "research",
        "Managed DeerFlow super-agent status, prepare, start, and query control.",
        aliases=("deerflow",),
    ),
    "crucix_control": ToolSpec(
        "crucix_control",
        "research",
        "Crucix live intelligence sweep status, briefings, ideas, and startup control.",
        aliases=("crucix",),
    ),
    "mirofish_control": ToolSpec(
        "mirofish_control",
        "research",
        "MiroFish market-simulation backend status and control.",
        aliases=("mirofish",),
    ),
    "autoresearch_control": ToolSpec(
        "autoresearch_control",
        "research",
        "Imported autoresearch experiment and results surface.",
        aliases=("autoresearch",),
    ),
    "lead_researcher": ToolSpec(
        "lead_researcher",
        "research",
        "Public lead and contact research over open web sources.",
    ),
    "comms_control": ToolSpec(
        "comms_control",
        "communications",
        "Unified communication hub for Telegram/desktop messaging plus SMTP email, SMS, and phone calls when configured.",
        aliases=("communications", "messaging", "email", "sms", "call", "phone"),
    ),
    "send_message": ToolSpec(
        "send_message",
        "communications",
        "Desktop-app/browser messaging automation for WhatsApp, Telegram, Instagram, and similar apps.",
        aliases=("message",),
    ),
    "browser_control": ToolSpec(
        "browser_control",
        "browser_vision",
        "Controlled browser navigation, search, clicks, typing, forms, and page-state inspection.",
        aliases=("browser",),
    ),
    "vision_tool": ToolSpec(
        "vision_tool",
        "browser_vision",
        "Screen or camera vision analysis with Gemini-backed visual reasoning.",
        aliases=("vision", "screen_process", "screen_processor", "vision_engine"),
    ),
    "computer_use": ToolSpec(
        "computer_use",
        "browser_vision",
        "Screen-grounded UI observation, find/click/type, and verification.",
        aliases=("computer",),
    ),
    "computer_control": ToolSpec(
        "computer_control",
        "browser_vision",
        "Low-level desktop typing, clicking, hotkeys, and screen interaction.",
    ),
    "cmd_control": ToolSpec(
        "cmd_control",
        "coding",
        "Real terminal execution across PowerShell, CMD, Bash, and VS Code terminal flows.",
        aliases=("terminal", "shell"),
    ),
    "file_controller": ToolSpec(
        "file_controller",
        "coding",
        "Read, write, create, move, copy, delete, and inspect files.",
        aliases=("files",),
    ),
    "code_helper": ToolSpec(
        "code_helper",
        "coding",
        "Focused single-file or script-level code generation, edits, execution, and explanation.",
    ),
    "codex_builder": ToolSpec(
        "codex_builder",
        "coding",
        "Runnable multi-file build generation for apps, websites, games, and larger artifacts.",
    ),
    "dev_agent": ToolSpec(
        "dev_agent",
        "coding",
        "General-purpose coding agent for development tasks.",
    ),
    "tradingagents_control": ToolSpec(
        "tradingagents_control",
        "trading",
        "TradingAgents runtime status, analysis, and MT5 handoff orchestration.",
        aliases=("tradingagents",),
    ),
    "predict_market": ToolSpec(
        "predict_market",
        "trading",
        "Market prediction by fusing AXIOM, Crucix, MiroFish, and TradingAgents context.",
        aliases=("market_predictor",),
    ),
    "mt5_trading": ToolSpec(
        "mt5_trading",
        "trading",
        "Native MetaTrader5 account inspection and order execution.",
        aliases=("mt5",),
    ),
    "trade_daemon_control": ToolSpec(
        "trade_daemon_control",
        "trading",
        "Persistent autonomous trading daemon control, status, and immediate-cycle triggers tied to MT5 Market Watch.",
        aliases=("trade_daemon", "trading_daemon"),
    ),
    "lightpanda_control": ToolSpec(
        "lightpanda_control",
        "integrations",
        "Optional Lightpanda backend status and launch guidance.",
        aliases=("lightpanda",),
    ),
    "paperclip_control": ToolSpec(
        "paperclip_control",
        "integrations",
        "Paperclip control-plane status and config surface.",
        aliases=("paperclip",),
    ),
    "openfang_control": ToolSpec(
        "openfang_control",
        "integrations",
        "OpenFang runtime status and control surface.",
        aliases=("openfang",),
    ),
    "symphony_control": ToolSpec(
        "symphony_control",
        "integrations",
        "Symphony orchestration/spec readiness surface.",
        aliases=("symphony",),
    ),
    "lossless_claw_control": ToolSpec(
        "lossless_claw_control",
        "integrations",
        "lossless-claw/OpenClaw plugin readiness surface.",
        aliases=("lossless_claw", "lossless-claw"),
    ),
    "dexter_control": ToolSpec(
        "dexter_control",
        "integrations",
        "Dexter imported runtime status and module count.",
        aliases=("dexter",),
    ),
    "pentagi_control": ToolSpec(
        "pentagi_control",
        "integrations",
        "PentAGI upstream/docs readiness and limitation surface.",
        aliases=("pentagi",),
    ),
    "automaton_control": ToolSpec(
        "automaton_control",
        "integrations",
        "Automaton runtime readiness, state, and configuration surface.",
        aliases=("automaton",),
    ),
    "persona_control": ToolSpec(
        "persona_control",
        "integrations",
        "PersonaPlex runtime and prompt surface.",
        aliases=("personaplex",),
    ),
}


_ALIAS_TO_TOOL: dict[str, str] = {}
for _tool_name, _spec in _TOOL_SPECS.items():
    _ALIAS_TO_TOOL[_tool_name] = _tool_name
    for _alias in _spec.aliases:
        _ALIAS_TO_TOOL[str(_alias).strip().lower().replace("-", "_")] = _tool_name


def canonical_tool_name(name: str) -> str:
    normalized = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIAS_TO_TOOL.get(normalized, normalized)


def tool_catalog_rows(category: str = "") -> list[dict]:
    selected = []
    want_category = str(category or "").strip().lower()
    for category_name in _CATEGORY_ORDER:
        for tool_name, spec in _TOOL_SPECS.items():
            if spec.category != category_name:
                continue
            if want_category and spec.category != want_category:
                continue
            selected.append(
                {
                    "name": spec.name,
                    "category": spec.category,
                    "description": spec.description,
                    "aliases": list(spec.aliases),
                }
            )
    return selected


def tool_alias_count() -> int:
    return sum(len(spec.aliases) for spec in _TOOL_SPECS.values())


def format_tool_catalog(limit: int = 0, category: str = "") -> str:
    rows = tool_catalog_rows(category=category)
    max_rows = int(limit or 0)
    if max_rows > 0:
        rows = rows[:max_rows]
    if not rows:
        return "AXIOM tool catalog: no tools matched that filter."

    lines = ["[AXIOM TOOL CATALOG]"]
    current_category = ""
    for row in rows:
        if row["category"] != current_category:
            current_category = row["category"]
            lines.append(f"{current_category}:")
        alias_text = f" | aliases: {', '.join(row['aliases'])}" if row["aliases"] else ""
        lines.append(f"- {row['name']}: {row['description']}{alias_text}")
    return "\n".join(lines)


def format_brain_surface(limit: int = 6) -> str:
    rows = tool_catalog_rows()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row["name"])

    lines = [
        "[AXIOM BRAIN MAP]",
        "Execution spine: intelligence_router -> planner -> executor -> tool_runtime -> runtime_store.",
        "Live state spine: system_capabilities -> doctor/integration bridges -> runtime memory/event traces.",
        "Adaptive spine: skill_library + agent_library + self_modifier + learning_orchestrator.",
        f"Registered canonical tools: {len(rows)} | aliases: {tool_alias_count()}",
    ]

    max_per_category = max(int(limit or 0), 1)
    for category_name in _CATEGORY_ORDER:
        tool_names = grouped.get(category_name, [])
        if not tool_names:
            continue
        preview = ", ".join(tool_names[:max_per_category])
        suffix = f", +{len(tool_names) - max_per_category} more" if len(tool_names) > max_per_category else ""
        lines.append(f"- {category_name}: {preview}{suffix}")
    return "\n".join(lines)
