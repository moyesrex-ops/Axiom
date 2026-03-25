import json
import re
import sys
import threading
import difflib
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan, reflect_and_improve
from agent.error_handler import analyze_error, generate_fix, ErrorDecision
from actions.self_modifier import get_dynamic_tool
from core.secret_config import get_gemini_api_key
from memory.memory_manager import save_to_nexus
from memory.runtime_store import log_event, search_knowledge_items, upsert_knowledge_item
from core.runtime_config import load_runtime_config


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
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
                print("[Executor] Injected translated content")

    return params

def _detect_language(text: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
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
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        target_lang = _detect_language(goal)
        print(f"[Executor] Translating to: {target_lang}")

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
        print(f"[Executor] Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Executor] Translation failed: {e}")
        return content

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."

    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Done."

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."

    elif tool == "cmd_control":
        from actions.cmd_control import cmd_control
        return cmd_control(parameters=parameters, player=None) or "Done."

    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "codex_builder":
        from actions.codex_builder import codex_builder
        return codex_builder(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Screen captured and analyzed."

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool in ("memory_archive", "nexus_memory"):
        from actions.nexus_memory import memory_archive
        return memory_archive(parameters=parameters, player=None) or "Done."

    elif tool == "deep_analyzer":
        from actions.deep_analyzer import deep_analyzer
        return deep_analyzer(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "autonomous_researcher":
        from actions.autonomous_researcher import autonomous_research
        return autonomous_research(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "mt5_trading":
        from actions.mt5_trading_agent import mt5_trading
        return mt5_trading(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "predict_market":
        from actions.market_predictor import predict_market
        return predict_market(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "mirofish_control":
        from actions.mirofish_control import mirofish_control
        return mirofish_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "tradingagents_control":
        from actions.tradingagents_control import tradingagents_control
        return tradingagents_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "self_modifier":
        from actions.self_modifier import self_modifier
        return self_modifier(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "system_capabilities":
        from actions.system_capabilities import system_capabilities
        return system_capabilities(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "automaton_control":
        from actions.automaton_control import automaton_control
        return automaton_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "skill_library":
        from actions.skill_library import skill_library
        return skill_library(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "agent_library":
        from actions.agent_library import agent_library
        return agent_library(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "lightpanda_control":
        from actions.lightpanda_control import lightpanda_control
        return lightpanda_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "autoresearch_control":
        from actions.autoresearch_control import autoresearch_control
        return autoresearch_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "deerflow_control":
        from actions.deerflow_control import deerflow_control
        return deerflow_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "paperclip_control":
        from actions.paperclip_control import paperclip_control
        return paperclip_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "openfang_control":
        from actions.openfang_control import openfang_control
        return openfang_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "symphony_control":
        from actions.symphony_control import symphony_control
        return symphony_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "lossless_claw_control":
        from actions.lossless_claw_control import lossless_claw_control
        return lossless_claw_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "dexter_control":
        from actions.dexter_control import dexter_control
        return dexter_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "pentagi_control":
        from actions.pentagi_control import pentagi_control
        return pentagi_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "persona_control":
        from actions.persona_control import persona_control
        return persona_control(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "prompt_studio":
        from actions.prompt_studio import prompt_studio
        return prompt_studio(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "lead_researcher":
        from actions.lead_researcher import lead_researcher
        return lead_researcher(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "swarm_orchestrator":
        from actions.swarm_orchestrator import swarm_orchestrator
        return swarm_orchestrator(parameters=parameters, player=None, speak=speak) or "Done."

    else:
        dynamic_tool = get_dynamic_tool(tool)
        if dynamic_tool is not None:
            return dynamic_tool(parameters=parameters, player=None, speak=speak) or "Done."
        raise ValueError(f"Unknown tool: {tool}")


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


def _autonomy_config() -> dict:
    return load_runtime_config().get("autonomy", {}) or {}


def _goal_word_count(goal: str) -> int:
    return len(re.findall(r"[a-z0-9]+", str(goal or "").lower()))


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
    if any(term in normalized for term in (" buy ", " sell ", " trade ", " order ", " execute_mt5", " website", " app", " game")):
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

    build_verbs = ("build", "create", "make", "design", "generate", "fix", "improve", "upgrade")
    build_targets = (
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
    )
    if any(verb in normalized for verb in build_verbs) and any(target in normalized for target in build_targets):
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
    ) -> str:
        print(f"\n[Executor] Goal: {goal}")

        specialist_context = _specialist_context(goal)
        direct = _direct_tool_for_goal(goal, specialist_context=specialist_context)
        if direct:
            tool, params = direct
            print(f"[Executor] Direct route: [{tool}] {params}")
            try:
                result = _call_tool(tool, params, speak)
                self._remember_task_strategy(
                    goal,
                    [{"step": 1, "tool": tool, "parameters": params, "description": goal}],
                    {1: result},
                    replanned=False,
                )
                return self._summarize(
                    goal,
                    [{"step": 1, "tool": tool, "parameters": params, "description": goal}],
                    {1: result},
                    speak,
                )
            except Exception as error:
                print(f"[Executor] Direct route failed, falling back to planner: {error}")

        replan_attempts = 0
        completed_steps = []
        step_results    = {}
        
        # 1. Draft
        plan = create_plan(goal, context=specialist_context)
        
        # 2. Reflection & Critique
        if "steps" in plan and len(plan["steps"]) > 0:
            plan = reflect_and_improve(goal, plan, context=specialist_context)

        while True:
            steps = plan.get("steps", [])

            if not steps:
                msg = "I couldn't create a valid plan for this task."
                if speak: speak(msg)
                return msg

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Task cancelled.")
                    return "Task cancelled."

                step_num = step.get("step", "?")
                tool     = step.get("tool") or "web_search"
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)

                print(f"\n[Executor] Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    try:
                        result = _call_tool(tool, params, speak)
                        step_results[step_num] = result
                        completed_steps.append(step)
                        print(f"[Executor] Step {step_num} done: {str(result)[:100]}")
                        step_ok = True
                        break

                    except Exception as e:
                        error_msg = str(e)
                        print(f"[Executor] Step {step_num} attempt {attempt} failed: {error_msg}")

                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")

                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            attempt += 1
                            import time; time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Executor] Skipping step {step_num}")
                            completed_steps.append(step)
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Task aborted. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            return msg

                        else:
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion:
                                try:
                                    fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                    if speak: speak("Trying an alternative approach.")
                                    res = _call_tool(
                                        fixed_step["tool"],
                                        fixed_step["parameters"],
                                        speak
                                    )
                                    step_results[step_num] = res
                                    completed_steps.append(step)
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    print(f"[Executor] Fix failed: {fix_err}")

                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False

                if not success:
                    break

            if success:
                self._remember_task_strategy(goal, completed_steps, step_results, replanned=bool(replan_attempts))

                if replan_attempts > 0:
                    topic = f"learned_strategy_{goal.replace(' ', '_')[:30]}"
                    learned_content = f"Goal: {goal}\nSuccessful sequence:\n" + "\n".join(
                        f"Step: {s['tool']}({s.get('parameters')})" for s in completed_steps
                    )
                    save_to_nexus(topic, learned_content)
                    if speak: speak("I learned from my mistakes and saved this strategy to my memory archive.")

                return self._summarize(goal, completed_steps, step_results, speak)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Task failed after {replan_attempts} replan attempts."
                if speak: speak(msg)
                return msg

            if speak: speak("Adjusting my approach.")

            replan_attempts += 1
            plan = replan(goal, completed_steps, failed_step, failed_error, context=specialist_context)

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
