import json
import re
import sys
import threading
import difflib
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan, reflect_and_improve
from agent.error_handler import analyze_error, generate_fix, ErrorDecision
from agent.completion_verifier import (
    verify_goal_completion,
    extract_and_save_lessons,
)
from core.tool_runtime import execute_tool
from core.secret_config import get_gemini_api_key
from memory.memory_manager import save_to_nexus
from memory.runtime_store import (
    append_task_event,
    log_event,
    search_knowledge_items,
    upsert_knowledge_item,
    upsert_task_step,
)
from core.runtime_config import load_runtime_config


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()


def _safe_print(message: str) -> None:
    text = str(message)
    try:
        print(text)
    except UnicodeEncodeError:
        stream = getattr(sys, "stdout", None)
        if stream is None:
            return
        encoding = getattr(stream, "encoding", None) or "utf-8"
        safe = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
        stream.write(safe + "\n")


_TRIVIAL_TOOL_RESULTS = {
    "",
    "done.",
    "completed.",
    "command executed with no output.",
    "screen captured and analyzed.",
}
_RGB_COLOR_HINTS = (
    "red",
    "green",
    "blue",
    "white",
    "yellow",
    "orange",
    "purple",
    "pink",
    "cyan",
    "off",
    "rainbow",
    "glowing",
)
_RGB_COLOR_ALIASES = {
    "grain": "green",
    "gren": "green",
    "greeen": "green",
    "blu": "blue",
    "bleu": "blue",
    "reed": "red",
}
_SPECIALIST_COMPLEXITY_HINTS = (
    "build",
    "create",
    "make",
    "design",
    "generate",
    "fix",
    "debug",
    "investigate",
    "research",
    "analyze",
    "review",
    "refactor",
    "deploy",
    "website",
    "site",
    "app",
    "game",
    "frontend",
    "backend",
    "dashboard",
    "security",
    "trading",
)
_SOFTWARE_GOAL_TARGETS = (
    "website",
    "site",
    "landing page",
    "portfolio",
    "dashboard",
    "web app",
    "app",
    "game",
    "playable",
    "snake",
    "arcade",
    "frontend",
    "backend",
    "script",
    "code",
    "program",
)
_SOFTWARE_BUILD_VERBS = ("build", "create", "make", "design", "generate", "fix", "improve", "upgrade")
_MARKET_TASK_HINTS = (
    "forex",
    "market",
    "markets",
    "mt5",
    "meta trader",
    "metatrader",
    "tradingagents",
    "trade",
    "trades",
    "sentiment",
    "currency",
    "gold",
    "silver",
    "eurusd",
    "xauusd",
)
_SOFTWARE_ONLY_TOOLS = {"codex_builder", "code_helper", "dev_agent"}
_APP_CONTROL_VERBS = {
    "open": ("open ", "launch ", "start "),
    "close": ("close ", "quit ", "exit "),
}
_MAIL_CHECK_PHRASES = (
    "check my mail",
    "check my email",
    "check my emails",
    "check my inbox",
    "go through my mail",
    "go through my mails",
    "go through my emails",
    "see if i have any mail",
    "see if i have any email",
    "see if i have any emails",
    "what emails do i have",
    "what email do i have",
    "what mail do i have",
)
_MAIL_READ_PHRASES = (
    "read this email",
    "read this mail",
    "read the email",
    "read the mail",
    "read my email",
    "read my mail",
    "check what this email says",
)
_MAIL_REPLY_PHRASES = (
    "reply to this email",
    "reply to this mail",
    "respond to this email",
    "respond to this mail",
    "draft a reply to this email",
    "draft a reply to this mail",
)


def _get_api_key() -> str:
    return get_gemini_api_key()

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                _safe_print("[Executor] Injected translated content")

    return params

def _detect_language(text: str) -> str:
    from core import gemini_compat as genai
    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")
    try:
        response = model.generate_content(
            f"What language is this text written in? "
            f"Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        from core import gemini_compat as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-3-flash-preview")

        target_lang = _detect_language(goal)
        _safe_print(f"[Executor] Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        response = model.generate_content(prompt)
        translated = response.text.strip()
        _safe_print(f"[Executor] Translation done ({target_lang})")
        return translated
    except Exception as e:
        _safe_print(f"[Executor] Translation failed: {e}")
        return content

def _call_tool(
    tool: str,
    parameters: dict,
    speak: Callable | None,
    metadata: dict | None = None,
) -> str:
    return execute_tool(
        tool,
        parameters,
        player=None,
        speak=speak,
        channel="task",
        source="agent_executor",
        metadata=metadata,
    )


def _extract_color_hint(text: str) -> str:
    normalized = str(text or "").lower()
    for color in _RGB_COLOR_HINTS:
        if re.search(rf"\b{re.escape(color)}\b", normalized):
            return color
    for token in re.findall(r"[a-z]+", normalized):
        if len(token) < 4:
            continue
        if token in _RGB_COLOR_ALIASES:
            return _RGB_COLOR_ALIASES[token]
        match = difflib.get_close_matches(token, list(_RGB_COLOR_HINTS), n=1, cutoff=0.72)
        if match:
            return match[0]
    return ""


def _extract_app_control_request(goal: str) -> tuple[str, str] | None:
    normalized = str(goal or "").strip().lower()
    if not normalized:
        return None

    action = ""
    remainder = ""
    for candidate, prefixes in _APP_CONTROL_VERBS.items():
        for prefix in prefixes:
            if normalized.startswith(prefix):
                action = candidate
                remainder = normalized[len(prefix):].strip()
                break
        if action:
            break

    if not action or not remainder:
        return None

    remainder = remainder.removeprefix("the ").strip()
    for suffix in (" application", " app", " program"):
        if remainder.endswith(suffix):
            remainder = remainder[: -len(suffix)].strip()

    try:
        from actions.open_app import _APP_ALIASES

        aliases = sorted(_APP_ALIASES.keys(), key=len, reverse=True)
    except Exception:
        aliases = []

    for alias in aliases:
        alias_text = str(alias or "").strip().lower()
        if not alias_text:
            continue
        if remainder == alias_text or remainder.startswith(alias_text + " ") or alias_text in remainder:
            return action, alias_text

    if len(remainder.split()) <= 2 and re.fullmatch(r"[a-z0-9 ._-]+", remainder):
        return action, remainder

    return None


def _extract_mail_reply_instruction(goal: str) -> str:
    raw = str(goal or "").strip()
    normalized = raw.lower()
    for marker in (" saying ", " say ", " telling them ", " tell them ", " with ", " that says "):
        if marker in normalized:
            return raw[normalized.index(marker) + len(marker) :].strip().strip("\"'")
    return ""


def _extract_mail_request(goal: str) -> tuple[str, dict] | None:
    normalized = str(goal or "").strip().lower()
    if not normalized:
        return None

    if any(_contains_phrase(normalized, phrase) for phrase in _MAIL_REPLY_PHRASES):
        instruction = _extract_mail_reply_instruction(goal)
        params = {
            "action": "gmail_reply_draft",
            "app_name": "mail",
            "open_if_needed": False,
        }
        if instruction:
            params["instruction"] = instruction
        return "comms_control", params

    if any(_contains_phrase(normalized, phrase) for phrase in _MAIL_READ_PHRASES):
        return "comms_control", {"action": "gmail_read", "app_name": "mail", "open_if_needed": False}

    if any(_contains_phrase(normalized, phrase) for phrase in _MAIL_CHECK_PHRASES):
        return "comms_control", {"action": "gmail_check", "app_name": "mail", "open_if_needed": True}

    return None


def _autonomy_config() -> dict:
    return load_runtime_config().get("autonomy", {}) or {}


def _goal_word_count(goal: str) -> int:
    return len(re.findall(r"[a-z0-9]+", str(goal or "").lower()))


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized = str(text or "").strip().lower()
    token = str(phrase or "").strip().lower()
    if not normalized or not token:
        return False
    if " " in token:
        return token in normalized
    return bool(re.search(rf"\b{re.escape(token)}\b", normalized))


def _goal_is_market_or_trading_task(goal: str) -> bool:
    normalized = str(goal or "").strip().lower()
    return any(_contains_phrase(normalized, token) for token in _MARKET_TASK_HINTS)


def _goal_is_software_build(goal: str) -> bool:
    normalized = str(goal or "").strip().lower()
    has_build_verb = any(_contains_phrase(normalized, verb) for verb in _SOFTWARE_BUILD_VERBS)
    has_software_target = any(_contains_phrase(normalized, target) for target in _SOFTWARE_GOAL_TARGETS)
    return has_build_verb and has_software_target


def _plan_violates_goal_domain(goal: str, plan: dict) -> bool:
    if not _goal_is_market_or_trading_task(goal):
        return False
    if _goal_is_software_build(goal):
        return False
    steps = list(plan.get("steps", []) or [])
    return any(str(step.get("tool", "") or "").strip() in _SOFTWARE_ONLY_TOOLS for step in steps)


def _should_prepare_specialists(goal: str) -> bool:
    cfg = _autonomy_config()
    if not bool(cfg.get("auto_specialists", True)):
        return False

    normalized = str(goal or "").strip().lower()
    if not normalized:
        return False

    min_words = int(cfg.get("specialist_task_min_words", 6) or 6)
    if any(hint in normalized for hint in _SPECIALIST_COMPLEXITY_HINTS):
        return True
    return _goal_word_count(normalized) >= max(min_words, 10)


def _learned_strategy_context(goal: str) -> str:
    cfg = _autonomy_config()
    if not bool(cfg.get("reuse_task_strategies", True)):
        return ""

    goal_text = str(goal or "").strip()
    if not goal_text:
        return ""

    limit = max(1, min(int(cfg.get("task_strategy_limit", 2) or 2), 4))
    try:
        rows = search_knowledge_items(goal_text, limit=limit, kinds=["task_strategy"])
    except Exception as error:
        log_event("executor", "strategy_context_failed", str(error)[:300])
        return ""

    if not rows:
        return ""

    lines = ["[LEARNED STRATEGIES]"]
    for row in rows[:limit]:
        title = str(row.get("title", "") or "Task Strategy").strip()
        content = str(row.get("content", "") or "").strip()
        if not content:
            continue
        compact = re.sub(r"\s+", " ", content)
        lines.append(f"- {title}: {compact[:480]}")

    if len(lines) == 1:
        return ""

    context = "\n".join(lines)
    log_event("executor", "strategy_context_built", goal_text[:240], metadata={"matches": len(lines) - 1})
    return context


def _specialist_context(goal: str) -> str:
    sections = []
    strategy_context = _learned_strategy_context(goal)
    if strategy_context:
        sections.append(strategy_context)

    if not _should_prepare_specialists(goal):
        return "\n\n".join(section for section in sections if section).strip()

    cfg = _autonomy_config()
    limit = max(1, min(int(cfg.get("specialist_limit", 2) or 2), 3))

    try:
        from core.skill_library import recommend_skill_library

        skills = recommend_skill_library(goal, limit=limit)
        if skills:
            lines = ["[RECOMMENDED SKILLS]"]
            for row in skills[:limit]:
                lines.append(
                    f"- {row['id']} | {row['name']} | {(row.get('description', '') or 'no summary')[:180]}"
                )
                preview = str(row.get("content_preview", "") or "").strip()
                if preview:
                    lines.append(f"  Guidance: {preview[:320]}")
            sections.append("\n".join(lines))
    except Exception as error:
        log_event("executor", "specialist_skill_context_failed", str(error)[:300])

    try:
        from core.agent_library import recommend_agent_library

        agents = recommend_agent_library(goal, limit=limit)
        if agents:
            lines = ["[RECOMMENDED AGENTS]"]
            for row in agents[:limit]:
                lines.append(
                    f"- {row['id']} | {row['name']} | {row['source_name']} | {row['category']} | "
                    f"{(row.get('description', '') or 'no summary')[:180]}"
                )
                preview = str(row.get("content_preview", "") or "").strip()
                if preview:
                    lines.append(f"  Excerpt: {preview[:320]}")
            sections.append("\n".join(lines))
    except Exception as error:
        log_event("executor", "specialist_agent_context_failed", str(error)[:300])

    context = "\n\n".join(section for section in sections if section).strip()
    if context:
        log_event("executor", "specialist_context_built", goal[:240], metadata={"chars": len(context)})
    return context


def _should_direct_research(goal: str) -> bool:
    normalized = str(goal or "").strip().lower()
    if not normalized:
        return False
    if any(_contains_phrase(normalized, term) for term in ("buy", "sell", "trade", "order", "execute_mt5", "website", "app", "game")):
        return False
    research_starts = (
        "research ",
        "analyze ",
        "investigate ",
        "deep research ",
        "deep dive ",
        "look into ",
        "compare ",
    )
    return any(normalized.startswith(prefix) for prefix in research_starts)


def _direct_tool_for_goal(goal: str, specialist_context: str = "") -> tuple[str, dict] | None:
    normalized = str(goal or "").strip().lower()
    if not normalized:
        return None

    app_request = _extract_app_control_request(goal)
    if app_request:
        action, app_name = app_request
        return ("open_app", {"action": action, "app_name": app_name})

    mail_request = _extract_mail_request(goal)
    if mail_request:
        return mail_request

    rgb_words = ("keyboard", "rgb", "lighting", "lights", "backlight", "color")
    color = _extract_color_hint(normalized)
    if color and any(word in normalized for word in rgb_words):
        return (
            "computer_settings",
            {
                "action": "change_hardware_color",
                "value": color,
                "description": goal,
            },
        )

    if any(phrase in normalized for phrase in ("show rgb", "rgb status", "keyboard lighting status")):
        return (
            "computer_settings",
            {
                "action": "hardware_rgb_status",
                "description": goal,
            },
        )

    if any(phrase in normalized for phrase in ("hardware status", "gpu status", "system hardware")):
        return (
            "computer_settings",
            {
                "action": "hardware_status",
                "description": goal,
            },
        )

    if _should_direct_research(goal):
        try:
            from core.deerflow_bridge import collect_deerflow_status

            deerflow = collect_deerflow_status(limit=2)
            if deerflow.get("proxy_reachable"):
                return (
                    "deerflow_control",
                    {
                        "action": "query",
                        "goal": goal,
                        "mode": "pro",
                    },
                )
        except Exception as error:
            log_event("executor", "deerflow_direct_route_probe_failed", str(error)[:300])

        context = "Run a deep multi-source research pass with concrete findings, citations, and next actions."
        if specialist_context:
            context += f"\n\nSpecialist guidance:\n{specialist_context[:1600]}"
        return (
            "web_search",
            {
                "query": goal,
                "mode": "deep",
                "context": context,
                "sources": ["web", "discussions"],
            },
        )

    if _goal_is_software_build(goal):
        open_when_done = any(
            phrase in normalized
            for phrase in ("open it", "open when done", "launch it", "show it", "playable", "browser")
        )
        description = goal
        if specialist_context:
            description = f"{goal}\n\nExecution guidance:\n{specialist_context[:3000]}"
        return (
            "codex_builder",
            {
                "action": "build",
                "description": description,
                "open_when_done": open_when_done,
            },
        )

    return None

class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
        task_id: str = "",
        task_metadata: dict | None = None,
        progress_callback: Callable | None = None,
    ) -> str:
        from agent.self_monitor import start_monitoring, get_monitor
        start_monitoring()
        if get_monitor().should_throttle():
            if speak: speak("High task volume detected. Pacing myself.")
            import time; time.sleep(3)

        _safe_print(f"\n[Executor] Goal: {goal}")
        base_task_metadata = dict(task_metadata or {})
        plan_revision = 0

        def _safe_step_index(value, fallback: int) -> int:
            try:
                return int(value)
            except Exception:
                return int(fallback)

        def _notify(
            topic: str,
            message: str,
            *,
            phase: str = "",
            step_index: int | None = None,
            step_total: int | None = None,
            tool: str = "",
            description: str = "",
            parameters: dict | None = None,
            step_status: str = "",
            result_text: str = "",
            error_text: str = "",
            revision: int | None = None,
            metadata: dict | None = None,
        ) -> None:
            payload = dict(base_task_metadata)
            payload.update(metadata or {})
            if revision not in (None, ""):
                payload["plan_revision"] = int(revision)
            if step_total not in (None, ""):
                payload["step_total"] = int(step_total)
            if description:
                payload["description"] = str(description)[:500]

            if task_id:
                append_task_event(
                    task_id,
                    topic,
                    str(message or "")[:4000],
                    phase=phase,
                    metadata=payload,
                )
                if step_index is not None:
                    upsert_task_step(
                        task_id,
                        int(step_index),
                        revision=max(int(revision or plan_revision or 1), 1),
                        tool=tool,
                        description=description,
                        status=step_status or topic,
                        parameters=parameters,
                        result_text=result_text,
                        error_text=error_text,
                        metadata=payload,
                    )

            if progress_callback:
                try:
                    progress_callback(
                        {
                            "topic": topic,
                            "message": str(message or ""),
                            "phase": phase,
                            "step_index": step_index,
                            "step_total": step_total,
                            "tool": tool,
                            "description": description,
                            "step_status": step_status or topic,
                            "plan_revision": revision or plan_revision,
                            "metadata": payload,
                        }
                    )
                except Exception:
                    pass

        def _publish_plan(plan_obj: dict, topic: str, message: str) -> int:
            nonlocal plan_revision
            plan_revision += 1
            steps = list(plan_obj.get("steps", []) or [])
            if task_id:
                for fallback_index, step in enumerate(steps, start=1):
                    step_index = _safe_step_index(step.get("step"), fallback_index)
                    upsert_task_step(
                        task_id,
                        step_index,
                        revision=plan_revision,
                        tool=str(step.get("tool", "") or ""),
                        description=str(step.get("description", "") or ""),
                        status="planned",
                        parameters=step.get("parameters", {}) or {},
                        metadata={
                            **base_task_metadata,
                            "critical": bool(step.get("critical", False)),
                            "phase": "planning",
                            "plan_revision": plan_revision,
                        },
                    )
            _notify(
                topic,
                message,
                phase="planning",
                step_total=len(steps),
                revision=plan_revision,
                metadata={"planned_steps": len(steps)},
            )
            return plan_revision

        _notify("executor_started", "Executor accepted the task.", phase="planning", revision=plan_revision)

        specialist_context = _specialist_context(goal)
        direct = _direct_tool_for_goal(goal, specialist_context=specialist_context)
        if direct:
            tool, params = direct
            _safe_print(f"[Executor] Direct route: [{tool}] {params}")
            try:
                _publish_plan(
                    {
                        "goal": goal,
                        "steps": [
                            {
                                "step": 1,
                                "tool": tool,
                                "description": goal,
                                "parameters": params,
                                "critical": True,
                            }
                        ],
                    },
                    "direct_route_selected",
                    f"Direct route selected: {tool}.",
                )
                _notify(
                    "step_started",
                    f"Starting direct step with {tool}.",
                    phase="executing",
                    step_index=1,
                    step_total=1,
                    tool=tool,
                    description=goal,
                    parameters=params,
                    step_status="running",
                    revision=plan_revision,
                )
                result = _call_tool(
                    tool,
                    params,
                    speak,
                    metadata={"goal": goal, "path": "direct_route", "description": goal},
                )
                _notify(
                    "step_completed",
                    f"Direct step completed with {tool}.",
                    phase="executing",
                    step_index=1,
                    step_total=1,
                    tool=tool,
                    description=goal,
                    parameters=params,
                    step_status="completed",
                    result_text=result,
                    revision=plan_revision,
                )
                self._remember_task_strategy(
                    goal,
                    [{"step": 1, "tool": tool, "parameters": params, "description": goal}],
                    {1: result},
                    replanned=False,
                )
                summary = self._summarize(
                    goal,
                    [{"step": 1, "tool": tool, "parameters": params, "description": goal}],
                    {1: result},
                    speak,
                )
                _notify(
                    "task_completed",
                    "Task completed through the direct route.",
                    phase="completed",
                    step_index=1,
                    step_total=1,
                    tool=tool,
                    description=goal,
                    result_text=summary,
                    revision=plan_revision,
                )
                return summary
            except Exception as error:
                _safe_print(f"[Executor] Direct route failed, falling back to planner: {error}")
                _notify(
                    "direct_route_failed",
                    f"Direct route failed: {str(error)[:300]}",
                    phase="planning",
                    tool=tool,
                    description=goal,
                    parameters=params,
                    error_text=str(error),
                    revision=plan_revision or 1,
                )

        replan_attempts = 0
        completed_steps = []
        step_results    = {}
        
        # 1. Draft
        plan = create_plan(goal, context=specialist_context)
        _publish_plan(plan, "plan_created", "Initial plan created.")
        
        # 2. Reflection & Critique
        if "steps" in plan and len(plan["steps"]) > 0:
            plan = reflect_and_improve(goal, plan, context=specialist_context)
            _publish_plan(plan, "plan_refined", "Planner reflection refined the execution plan.")

        if _plan_violates_goal_domain(goal, plan):
            guard_context = (
                specialist_context + "\n\n" if specialist_context else ""
            ) + (
                "[DOMAIN GUARDRAIL]\n"
                "This is a market/trading task, not a software build.\n"
                "Do not use codex_builder, code_helper, or dev_agent unless the user explicitly asked for code or a software artifact.\n"
                "Prefer tradingagents_control, predict_market, deep_analyzer, web_search, system_capabilities, and mt5_trading when appropriate."
            )
            log_event("executor", "plan_domain_violation", goal[:300], metadata={"plan_tools": [step.get("tool", "") for step in plan.get("steps", [])]})
            _notify(
                "plan_domain_violation",
                "Planner proposed tools outside the task domain, regenerating plan.",
                phase="planning",
                revision=plan_revision,
                metadata={"plan_tools": [step.get("tool", "") for step in plan.get("steps", [])]},
            )
            plan = create_plan(goal, context=guard_context)
            _publish_plan(plan, "plan_regenerated", "Domain guard regenerated the plan.")
            if "steps" in plan and len(plan["steps"]) > 0:
                plan = reflect_and_improve(goal, plan, context=guard_context)
                _publish_plan(plan, "plan_refined", "Domain-guard reflection refined the regenerated plan.")

        if _plan_violates_goal_domain(goal, plan):
            msg = (
                "I stopped before executing because the planner kept trying coding/build tools for a market or trading task. "
                "No fake build was run."
            )
            if speak:
                speak(msg)
            _notify(
                "task_failed",
                msg,
                phase="failed",
                revision=plan_revision,
            )
            return msg

        while True:
            steps = plan.get("steps", [])

            if not steps:
                msg = "I couldn't create a valid plan for this task."
                if speak: speak(msg)
                _notify("task_failed", msg, phase="failed", revision=plan_revision)
                return msg

            success      = True
            failed_step  = None
            failed_error = ""
            total_steps = len(steps)

            for fallback_index, step in enumerate(steps, start=1):
                if cancel_flag and cancel_flag.is_set():
                    msg = "Task cancelled."
                    if speak:
                        speak(msg)
                    _notify("task_cancelled", msg, phase="cancelled", revision=plan_revision)
                    return msg

                step_num = _safe_step_index(step.get("step"), fallback_index)
                tool     = step.get("tool") or "web_search"
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)

                _safe_print(f"\n[Executor] Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    _notify(
                        "step_started",
                        f"Starting step {step_num} with {tool}.",
                        phase="executing",
                        step_index=step_num,
                        step_total=total_steps,
                        tool=tool,
                        description=desc,
                        parameters=params,
                        step_status="running",
                        revision=plan_revision,
                        metadata={"attempt": attempt},
                    )
                    try:
                        from agent.self_monitor import start_task_tracking, end_task_tracking
                        start_task_tracking(f"[{tool}] {desc[:30]}")
                        
                        result = _call_tool(
                            tool,
                            params,
                            speak,
                            metadata={
                                "goal": goal,
                                "step": step_num,
                                "description": desc,
                                "path": "plan_step",
                            },
                        )
                        
                        end_task_tracking(success=True)
                        step_results[step_num] = result
                        completed_steps.append(step)
                        _safe_print(f"[Executor] Step {step_num} done: {str(result)[:100]}")
                        _notify(
                            "step_completed",
                            f"Step {step_num} completed with {tool}.",
                            phase="executing",
                            step_index=step_num,
                            step_total=total_steps,
                            tool=tool,
                            description=desc,
                            parameters=params,
                            step_status="completed",
                            result_text=result,
                            revision=plan_revision,
                        )
                        step_ok = True
                        break

                    except Exception as e:
                        try:
                            from agent.self_monitor import end_task_tracking
                            end_task_tracking(success=False)
                        except Exception:
                            pass
                        error_msg = str(e)
                        _safe_print(f"[Executor] Step {step_num} attempt {attempt} failed: {error_msg}")
                        recovery = analyze_error(step, error_msg, attempt=attempt, max_attempts=3)
                        decision = recovery.get("decision", ErrorDecision.REPLAN)
                        if isinstance(decision, str):
                            decision = {
                                "retry": ErrorDecision.RETRY,
                                "skip": ErrorDecision.SKIP,
                                "replan": ErrorDecision.REPLAN,
                                "abort": ErrorDecision.ABORT,
                            }.get(decision.strip().lower(), ErrorDecision.REPLAN)
                        user_msg = str(recovery.get("user_message", "") or "").strip()
                        decision_name = decision.value if isinstance(decision, ErrorDecision) else str(decision)
                        _notify(
                            "step_failed",
                            f"Step {step_num} failed: {error_msg[:300]}",
                            phase="executing",
                            step_index=step_num,
                            step_total=total_steps,
                            tool=tool,
                            description=desc,
                            parameters=params,
                            step_status="failed",
                            error_text=error_msg,
                            revision=plan_revision,
                            metadata={
                                "attempt": attempt,
                                "decision": decision_name,
                                "reason": str(recovery.get("reason", "") or "")[:300],
                            },
                        )
                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            _notify(
                                "step_retry",
                                f"Retrying step {step_num}.",
                                phase="executing",
                                step_index=step_num,
                                step_total=total_steps,
                                tool=tool,
                                description=desc,
                                parameters=params,
                                step_status="retrying",
                                error_text=error_msg,
                                revision=plan_revision,
                                metadata={"attempt": attempt + 1},
                            )
                            attempt += 1
                            import time; time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            _safe_print(f"[Executor] Skipping step {step_num}")
                            step_results[step_num] = "Skipped by recovery policy."
                            completed_steps.append(step)
                            _notify(
                                "step_skipped",
                                f"Step {step_num} skipped after recovery analysis.",
                                phase="executing",
                                step_index=step_num,
                                step_total=total_steps,
                                tool=tool,
                                description=desc,
                                parameters=params,
                                step_status="skipped",
                                result_text="Skipped by recovery policy.",
                                revision=plan_revision,
                            )
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Task aborted. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            _notify("task_failed", msg, phase="failed", revision=plan_revision)
                            return msg

                        else:
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion:
                                try:
                                    fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                    _notify(
                                        "recovery_step_started",
                                        f"Trying recovery step for original step {step_num}.",
                                        phase="fixing",
                                        step_index=step_num,
                                        step_total=total_steps,
                                        tool=fixed_step.get("tool", tool),
                                        description=fixed_step.get("description", desc),
                                        parameters=fixed_step.get("parameters", {}),
                                        step_status="running",
                                        error_text=error_msg,
                                        revision=plan_revision,
                                    )
                                    if speak: speak("Trying an alternative approach.")
                                    res = _call_tool(
                                        fixed_step["tool"],
                                        fixed_step["parameters"],
                                        speak,
                                        metadata={
                                            "goal": goal,
                                            "step": step_num,
                                            "description": fixed_step.get("description", desc),
                                            "path": "recovery_step",
                                        },
                                    )
                                    step_results[step_num] = res
                                    completed_steps.append(step)
                                    _notify(
                                        "recovery_step_completed",
                                        f"Recovery step completed for original step {step_num}.",
                                        phase="fixing",
                                        step_index=step_num,
                                        step_total=total_steps,
                                        tool=fixed_step.get("tool", tool),
                                        description=fixed_step.get("description", desc),
                                        parameters=fixed_step.get("parameters", {}),
                                        step_status="completed",
                                        result_text=res,
                                        revision=plan_revision,
                                    )
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    _safe_print(f"[Executor] Fix failed: {fix_err}")
                                    _notify(
                                        "recovery_step_failed",
                                        f"Recovery step failed: {str(fix_err)[:300]}",
                                        phase="fixing",
                                        step_index=step_num,
                                        step_total=total_steps,
                                        tool=fixed_step.get("tool", tool) if 'fixed_step' in locals() else tool,
                                        description=fixed_step.get("description", desc) if 'fixed_step' in locals() else desc,
                                        parameters=fixed_step.get("parameters", {}) if 'fixed_step' in locals() else params,
                                        step_status="failed",
                                        error_text=str(fix_err),
                                        revision=plan_revision,
                                    )

                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False
                    _notify(
                        "step_failed",
                        f"Step {step_num} exhausted retries.",
                        phase="executing",
                        step_index=step_num,
                        step_total=total_steps,
                        tool=tool,
                        description=desc,
                        parameters=params,
                        step_status="failed",
                        error_text=failed_error,
                        revision=plan_revision,
                    )

                if not success:
                    break

            if success:
                self._remember_task_strategy(goal, completed_steps, step_results, replanned=bool(replan_attempts))

                # Phase 2: Post-execution verification
                try:
                    _notify(
                        "verification_started",
                        "Running completion verification.",
                        phase="verifying",
                        step_total=total_steps,
                        revision=plan_revision,
                    )
                    report = verify_goal_completion(goal, completed_steps, step_results)
                    extract_and_save_lessons(goal, report, completed_steps)

                    if not report.is_complete and report.confidence < 0.6 and replan_attempts < self.MAX_REPLAN_ATTEMPTS:
                        # Verification says incomplete; try to fix
                        _safe_print(f"[Executor] WARNING verifier flagged incomplete ({report.confidence:.0%}): {report.missing_items}")
                        _notify(
                            "verification_incomplete",
                            f"Verification flagged missing items: {', '.join(report.missing_items[:3])}",
                            phase="fixing",
                            step_total=total_steps,
                            revision=plan_revision,
                            metadata={
                                "confidence": float(report.confidence),
                                "missing_items": report.missing_items[:5],
                            },
                        )
                        if speak:
                            speak("Let me double-check - I'm not confident this is fully done.")
                        replan_attempts += 1
                        missing_context = (
                            f"Previous attempt was evaluated as INCOMPLETE. "
                            f"Missing items: {', '.join(report.missing_items[:3])}. "
                            f"Please add the missing steps."
                        )
                        plan = create_plan(goal, context=(specialist_context + "\n" + missing_context)[:3000])
                        _publish_plan(plan, "verification_replan_created", "Verification requested a new plan.")
                        if "steps" in plan and len(plan["steps"]) > 0:
                            plan = reflect_and_improve(goal, plan, context=specialist_context)
                            _publish_plan(plan, "verification_replan_refined", "Reflection refined the verification-driven replan.")
                        continue  # Re-enter the execution loop

                    _notify(
                        "verification_passed",
                        "Completion verification passed.",
                        phase="verifying",
                        step_total=total_steps,
                        revision=plan_revision,
                        metadata={
                            "confidence": float(report.confidence),
                            "missing_items": report.missing_items[:5],
                        },
                    )

                except Exception as verify_error:
                    _safe_print(f"[Executor] WARNING verification error (non-blocking): {verify_error}")
                    _notify(
                        "verification_error",
                        f"Verification raised a non-blocking error: {str(verify_error)[:300]}",
                        phase="verifying",
                        step_total=total_steps,
                        revision=plan_revision,
                    )

                if replan_attempts > 0:
                    topic = f"learned_strategy_{goal.replace(' ', '_')[:30]}"
                    learned_content = f"Goal: {goal}\nSuccessful sequence:\n" + "\n".join(
                        f"Step: {s['tool']}({s.get('parameters')})" for s in completed_steps
                    )
                    save_to_nexus(topic, learned_content)
                    if speak: speak("I learned from my mistakes and saved this strategy to my memory archive.")

                summary = self._summarize(goal, completed_steps, step_results, speak)
                _notify(
                    "task_completed",
                    "Task completed successfully.",
                    phase="completed",
                    step_total=total_steps,
                    result_text=summary,
                    revision=plan_revision,
                )
                return summary

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Task failed after {replan_attempts} replan attempts."
                # Phase 2: Log failure for learning
                log_event(
                    "failure",
                    "task_failed",
                    f"{goal[:300]} - failed after {replan_attempts} replans",
                    metadata={"failed_step": str(failed_step or {}).get("tool", "unknown"), "error": failed_error[:300]},
                )
                _notify(
                    "task_failed",
                    msg,
                    phase="failed",
                    tool=str((failed_step or {}).get("tool", "") or ""),
                    description=str((failed_step or {}).get("description", "") or ""),
                    error_text=failed_error,
                    revision=plan_revision,
                )
                if speak: speak(msg)
                return msg

            if speak: speak("Adjusting my approach.")

            replan_attempts += 1
            _notify(
                "replan_requested",
                f"Replanning after failure on step {str((failed_step or {}).get('step', '?'))}.",
                phase="fixing",
                tool=str((failed_step or {}).get("tool", "") or ""),
                description=str((failed_step or {}).get("description", "") or ""),
                error_text=failed_error,
                revision=plan_revision,
            )
            plan = replan(goal, completed_steps, failed_step, failed_error, context=specialist_context)
            _publish_plan(plan, "replan_created", "Replan created after step failure.")

    def _remember_task_strategy(
        self,
        goal: str,
        completed_steps: list,
        step_results: dict,
        replanned: bool = False,
    ) -> None:
        cfg = _autonomy_config()
        if not bool(cfg.get("save_task_strategies", True)):
            return

        goal_text = str(goal or "").strip()
        if not goal_text:
            return

        lines = [f"Goal: {goal_text}", f"Replanned: {'yes' if replanned else 'no'}", "Steps:"]
        tools = []
        for step in completed_steps[:8]:
            tool = str(step.get("tool", "") or "").strip()
            desc = str(step.get("description", "") or "").strip()
            tools.append(tool)
            lines.append(f"- {tool}: {desc[:220]}")

        useful = []
        for step in completed_steps[:8]:
            step_num = step.get("step", "")
            raw = str(step_results.get(step_num, "") or "").strip()
            compact = self._compact_result(raw)
            if compact:
                useful.append(f"- {step.get('tool', '')}: {compact[:600]}")
        if useful:
            lines.append("Key outputs:")
            lines.extend(useful[:5])

        upsert_knowledge_item(
            kind="task_strategy",
            title=f"Task Strategy: {goal_text[:80]}",
            content="\n".join(lines)[:12000],
            source="agent.executor",
            metadata={
                "goal": goal_text[:300],
                "tools": [tool for tool in tools if tool][:8],
                "replanned": bool(replanned),
            },
        )
        log_event("learning", "task_strategy_saved", goal_text[:300], metadata={"replanned": bool(replanned)})

    def _summarize(
        self,
        goal: str,
        completed_steps: list,
        step_results: dict,
        speak: Callable | None,
    ) -> str:
        useful_results = []
        for step in completed_steps:
            step_num = step.get("step", "")
            tool = str(step.get("tool", "") or "").strip()
            raw = str(step_results.get(step_num, "") or "").strip()
            compact = self._compact_result(raw)
            if compact:
                useful_results.append((tool, compact))

        if not useful_results:
            summary = f"Task complete. Completed {len(completed_steps)} steps for: {goal[:120]}"
            if speak:
                speak(summary)
            return summary

        if len(useful_results) == 1:
            summary = useful_results[0][1]
            if speak:
                speak(summary[:220])
            return summary

        lines = [f"Task complete: {goal}", "Useful results:"]
        for tool, text in useful_results[:4]:
            lines.append(f"- [{tool}] {text}")
        if len(useful_results) > 4:
            lines.append(f"- ... {len(useful_results) - 4} more step results recorded")
        summary = "\n".join(lines)
        if speak:
            speak("Task complete. I have the concrete results ready.")
        return summary

    @staticmethod
    def _compact_result(result: str) -> str:
        text = str(result or "").strip()
        if not text:
            return ""

        normalized = text.lower().strip()
        if normalized in _TRIVIAL_TOOL_RESULTS:
            return ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        keep = []
        important_prefixes = (
            "saved to:",
            "last code saved to:",
            "opened:",
            "file created:",
            "written to:",
            "appended to:",
            "run log:",
            "project directory:",
            "entry file:",
            "open target:",
            "url:",
            "link:",
            "output:",
            "order placed!",
            "mt5 connected.",
        )
        for line in lines:
            lower = line.lower()
            if lower.startswith(important_prefixes):
                keep.append(line)
            elif "http://" in line or "https://" in line:
                keep.append(line)
            elif "saved to " in lower or "opened in vscode at " in lower:
                keep.append(line)

        if keep:
            return "\n".join(keep[:6])

        if len(text) <= 700:
            return text
        return text[:697].rstrip() + "..."
